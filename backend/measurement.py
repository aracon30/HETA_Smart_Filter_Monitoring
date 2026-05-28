"""
Messzyklus – läuft als Daemon-Thread.

Kapselt den Mess-Loop und die zugehörigen Zustandsvariablen.
"""
import json
import logging
import time
from dataclasses import dataclass

from calculations import (
    STATUS_FEHLER,
    STATUS_OK,
    STATUS_WARNUNG,
    STATUS_WECHSEL,
    STATUS_WECHSEL_BESTAETIGEN,
    calculate_filter_health_from_r_eff,
    calculate_filter_state,
)

logger = logging.getLogger(__name__)


@dataclass
class MeasurementState:
    """Mutable Zustandsvariablen des Mess-Threads (ersetzt drei Module-Globals in app.py)."""
    smoothed_health_pct: float | None = None
    flow_stable_since:   float | None = None
    flow_below_since:    float | None = None


class MeasurementLoop:
    """
    Kapselt _measurement_loop() und _do_confirm_filter_change().

    Alle Abhängigkeiten werden im Konstruktor übergeben.
    _services hält die veränderbaren Referenzen auf mqtt und modbus
    (werden nach Einstellungsänderung vom Hauptthread aktualisiert).
    """

    def __init__(
        self,
        *,
        state: dict,
        state_lock,
        settings: dict,
        db,
        learning,
        predictor,
        dp_rate_buffer,
        sensor_manager=None,
        sim_manager=None,
        display=None,
        display_ctrl=None,
        # Veränderliche Referenzen (Wörterbuch, damit Neuzuweisung sichtbar ist)
        services: dict,            # {"mqtt": ..., "modbus": ...}
        # Callbacks aus app.py
        fn_read_sensors,
        fn_update_auto_thresholds,
        fn_seed_predictor,
        fn_get_flow_thresholds,
        fn_get_sim_rates,
        fn_get_sim_cycle_secs,
        fn_generate_service_rec,
        fn_reset_simulation,
        fn_get_status_display_data=None,   # falls benötigt; sonst None
    ):
        self._state        = state
        self._state_lock   = state_lock
        self._settings     = settings
        self._db           = db
        self._learning     = learning
        self._predictor    = predictor
        self._dp_rate_buffer = dp_rate_buffer
        self._sensor_mgr   = sensor_manager
        self._sim_mgr      = sim_manager
        self._display      = display
        self._display_ctrl = display_ctrl
        self._services     = services

        # Callbacks
        self._read_sensors              = fn_read_sensors
        self._update_auto_thresholds    = fn_update_auto_thresholds
        self._seed_predictor            = fn_seed_predictor
        self._get_flow_thresholds       = fn_get_flow_thresholds
        self._get_sim_rates             = fn_get_sim_rates
        self._get_sim_cycle_secs        = fn_get_sim_cycle_secs
        self._generate_service_rec      = fn_generate_service_rec
        self._reset_simulation          = fn_reset_simulation

        # Mutable loop state
        self.mstate = MeasurementState()

    def run(self):
        """Messzyklus-Thread-Einstiegspunkt (ehemals _measurement_loop in app.py)."""
        interval = self._settings.get("sampling_interval_seconds", 1)

        logger.info("Messzyklus gestartet (Intervall: %ds).", interval)
        self._dp_rate_buffer.clear()

        while self._state["running"]:
            t_start = time.time()
            # dp_limit aus Einstellungen; dp_clean aus gemessenem Profil (Ø start_dp
            # der Lernzyklen), Fallback auf Einstellungswert solange kein Profil.
            dp_limit = self._settings.get("dp_limit_bar", 2.5)
            _loop_profile = self._learning.get_profile(self._state.get("heta_code", ""))
            dp_clean = ((_loop_profile.get("reference_dp_clean") or 0.0)
                        if _loop_profile and (_loop_profile.get("reference_dp_clean") or 0.0) > 0
                        else self._settings.get("dp_clean_bar", 0.2))

            with self._state_lock:
                sim_mode          = self._state["simulation_mode"]
                awaiting          = self._state["awaiting_confirmation"]
                heta_code         = self._state["heta_code"]
                heta_activated    = self._state["heta_activated"]
                cycle_active      = self._state["cycle_active"]
                waiting_for_flow  = self._state["waiting_for_flow"]
                cycle_paused      = self._state["cycle_paused"]

            if awaiting:
                time.sleep(interval)
                continue

            # Sensoren lesen
            readings = self._read_sensors(
                simulation=sim_mode,
                pressure_range=self._settings.get("pressure_range_bar", 10.0),
                temperature_min=self._settings.get("temperature_min_c", -50.0),
                temperature_max=self._settings.get("temperature_max_c", 150.0),
                flow_max=self._settings.get("flow_max_l_min", 150.0),
            )

            p1 = readings["p1"]
            p2 = readings["p2"]
            temp = readings["temperature"]
            flow = readings["flow"]
            sensor_mode = readings["mode"]

            # Sensorfehler im Hardwaremodus: Messung sofort stoppen, Bediener informieren
            if sensor_mode == "sensor_fault":
                failed_ch = readings.get("failed_channels", [])
                failed_names = readings.get("failed_names", [])
                msg = f"Sensorfehler: {', '.join(failed_names)} – Messung gestoppt."
                logger.error("Messung gestoppt wegen Sensorfehler auf Kanal(en) %s.", failed_ch)
                self._learning.abort_cycle()
                with self._state_lock:
                    self._state["running"]               = False
                    self._state["sensor_fault"]          = True
                    self._state["sensor_fault_channels"] = failed_ch
                    self._state["sensor_fault_message"]  = msg
                    self._state["filter_status"]         = "FEHLER"
                    self._state["sensor_error"]          = True
                    self._state["cycle_active"]          = False
                    self._state["cycle_start_time"]      = None
                    self._state["cycle_dp_reached_time"] = None
                    self._state["last_update"]           = time.strftime("%Y-%m-%dT%H:%M:%S")
                break

            sensor_error = not (p1.is_valid and p2.is_valid and temp.is_valid and flow.is_valid)

            # Plausibilitätsprüfung im Realbetrieb: p2 > p1 ist physikalisch nicht möglich
            if (sensor_mode == "hardware" and not sensor_error
                    and p1.is_valid and p2.is_valid
                    and p2.value > p1.value + 0.05):
                logger.warning(
                    "Plausibilitätswarnung: p2 (%.3f bar) > p1 (%.3f bar) – "
                    "Sensorkabel vertauscht oder Druckverhältnisse unplausibel.",
                    p2.value, p1.value,
                )

            # Berechnungen
            # dp_direct: Simulationsmodus liefert dp als Primärwert – verhindert
            # Gleitkomma-Artefakte durch p1-p2-Subtraktion in calculate_filter_state.
            dp_direct = readings.get("dp_direct")
            fs = calculate_filter_state(
                p1_bar=p1.value,
                p2_bar=p2.value,
                flow_l_min=flow.value,
                temperature_c=temp.value,
                dp_clean=dp_clean,
                dp_limit=dp_limit,
                awaiting_confirmation=awaiting,
                sensor_error=sensor_error,
                anomaly_active=self._state["anomaly_active"],
                anomaly_percent=self._state["anomaly_percent"],
                dp_override=dp_direct,
            )

            # ── Profil laden (einmalig pro Loop-Iteration) ────────────────────
            profile       = self._learning.get_profile(heta_code) if heta_code else None
            profile_valid = bool(profile and profile.get("profile_valid")) and heta_activated
            cycles_count  = (profile.get("cycles_count", 0) if profile else 0) if heta_code else 0

            # ── Beladungsgrad via R_eff ──────────────────────────────────────
            # Bevorzugt R_eff-basiert (reagiert auf Δp UND Durchflussänderungen).
            # Ratchet: schnell steigen (Filter beladen), langsam fallen.
            # R_eff-basierter Beladungsgrad nur wenn Profil VALIDE ist –
            # während der Lernphase bleibt die dp-Formel aktiv, damit
            # kein Methodenwechsel mitten im Lernzyklus auftritt.
            r_eff_clean_ref = r_eff_limit_ref = None
            if profile_valid and profile:
                r_eff_clean_ref = (profile.get("reference_r_eff_start")
                                   or profile.get("reference_r_eff"))
                r_eff_limit_ref = profile.get("reference_r_eff_end") or 0.0
                if not r_eff_limit_ref:
                    # Fallback für alte Profile ohne reference_r_eff_end
                    ref_flow = profile.get("reference_avg_flow") or 0.0
                    if ref_flow > 0.1:
                        r_eff_limit_ref = dp_limit / ref_flow

            if r_eff_clean_ref and r_eff_limit_ref and fs.r_eff > 0:
                raw_health, _ = calculate_filter_health_from_r_eff(
                    fs.r_eff, r_eff_clean_ref, r_eff_limit_ref
                )
            else:
                raw_health = fs.filter_health_percent  # Fallback: dp-basiert

            if self.mstate.smoothed_health_pct is None:
                self.mstate.smoothed_health_pct = raw_health
            elif raw_health < self.mstate.smoothed_health_pct:
                # Filter belädt sich → health sinkt → leicht geglättet (schnell)
                self.mstate.smoothed_health_pct += 0.35 * (raw_health - self.mstate.smoothed_health_pct)
            else:
                # Filter könnte sich scheinbar verbessern → sehr langsam (max 0.3 %/s)
                self.mstate.smoothed_health_pct = min(raw_health, self.mstate.smoothed_health_pct + 0.3)

            smoothed_health = round(self.mstate.smoothed_health_pct, 1)

            # ── Durchfluss-Zustandsmaschine ───────────────────────────────────
            flow_thr, stab_secs, pause_tol = self._get_flow_thresholds()
            flow_ok = (fs.flow_l_min >= flow_thr and fs.dp_bar >= dp_clean * 0.5
                       and not sensor_error)
            now_ts  = time.time()

            # Im Simulationsmodus: Durchflussprüfung komplett deaktivieren.
            # Die Simulation steuert den Durchfluss intern – das Warten auf
            # stabilen Fluss würde Schnellstart und Lernzyklen blockieren.
            if sim_mode:
                if waiting_for_flow:
                    self.mstate.flow_stable_since = None
                    if heta_code:
                        self._learning.start_cycle(heta_code, fs.r_eff, fs.dp_bar)
                        self._seed_predictor(heta_code)
                    with self._state_lock:
                        self._state["waiting_for_flow"]     = False
                        self._state["cycle_active"]         = bool(heta_code)
                        self._state["cycle_start_time"]     = now_ts
                        self._state["cycle_active_seconds"] = 0.0
                        self._state["cycle_paused"]         = False
                    waiting_for_flow = False
                    cycle_active     = bool(heta_code)
                    cycle_paused     = False
                elif cycle_paused:
                    with self._state_lock:
                        self._state["cycle_paused"]           = False
                        self._state["cycle_pause_start_time"] = None
                    cycle_paused = False

            elif waiting_for_flow and not awaiting:
                # Overlay-Werte für Frontend live aktualisieren
                stable_pct = 0
                if flow_ok:
                    if self.mstate.flow_stable_since is None:
                        self.mstate.flow_stable_since = now_ts
                    elapsed_stable = now_ts - self.mstate.flow_stable_since
                    stable_pct = min(100, int(elapsed_stable / max(stab_secs, 1) * 100))
                    if elapsed_stable >= stab_secs:
                        # Bedingung stabil lang genug → Zyklus starten
                        self.mstate.flow_stable_since = None
                        self.mstate.flow_below_since  = None
                        if heta_code:
                            self._learning.start_cycle(heta_code, fs.r_eff, fs.dp_bar)
                            self._seed_predictor(heta_code)
                        with self._state_lock:
                            self._state["waiting_for_flow"]    = False
                            self._state["cycle_active"]        = bool(heta_code)
                            self._state["cycle_start_time"]    = now_ts
                            self._state["cycle_active_seconds"] = 0.0
                        cycle_active     = bool(heta_code)
                        waiting_for_flow = False
                        logger.info("Durchfluss stabil – Zyklus gestartet (Q=%.1f l/min, dp=%.3f bar).",
                                    fs.flow_l_min, fs.dp_bar)
                else:
                    self.mstate.flow_stable_since = None  # Stabilitätsfenster zurücksetzen

                with self._state_lock:
                    self._state["flow_check_q"]   = round(fs.flow_l_min, 1)
                    self._state["flow_check_dp"]  = round(fs.dp_bar, 3)
                    self._state["flow_threshold"] = round(flow_thr, 1)
                    self._state["flow_stable_pct"] = stable_pct

                if waiting_for_flow:
                    # Display-Update und Weiter im Loop (keine Messwert-Aufzeichnung)
                    if self._display:
                        self._display.show_waiting_for_flow(
                            fs.flow_l_min, flow_thr, fs.dp_bar, dp_clean * 0.5,
                            stable_pct, stab_secs,
                        )
                    with self._state_lock:
                        self._state["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    time.sleep(interval)
                    continue

            elif not sim_mode and cycle_paused and not awaiting:
                if flow_ok:
                    if self.mstate.flow_stable_since is None:
                        self.mstate.flow_stable_since = now_ts
                    if now_ts - self.mstate.flow_stable_since >= stab_secs:
                        # Zyklus fortsetzen
                        pause_dur = now_ts - (self._state.get("cycle_pause_start_time") or now_ts)
                        self.mstate.flow_stable_since = None
                        self.mstate.flow_below_since  = None
                        op_label = "Batch-Pause" if self._settings.get("operation_mode") == "batch" else "Unterbrechung"
                        self._learning.close_event(category="pause")
                        self._db.insert_service_event("ZYKLUS_PAUSE_ENDE", heta_code,
                                                f"{op_label} nach {pause_dur:.0f} s beendet")
                        with self._state_lock:
                            self._state["cycle_paused"]           = False
                            self._state["cycle_pause_start_time"] = None
                        cycle_paused = False
                        logger.info("Zyklus fortgesetzt nach %.0f s Pause.", pause_dur)
                else:
                    self.mstate.flow_stable_since = None
                    # Maximale Pausendauer prüfen
                    pause_start = self._state.get("cycle_pause_start_time") or now_ts
                    max_pause   = self._settings.get("flow_max_pause_days", 7) * 86400
                    if now_ts - pause_start >= max_pause:
                        logger.warning("Maximale Pausendauer überschritten – Zyklus abgebrochen.")
                        self._learning.abort_cycle()
                        self._db.insert_service_event("ZYKLUS_ABGEBROCHEN", heta_code,
                                                f"Kein Durchfluss seit {max_pause/86400:.0f} Tagen")
                        with self._state_lock:
                            self._state["cycle_paused"]           = False
                            self._state["cycle_active"]           = False
                            self._state["cycle_pause_start_time"] = None
                            self._state["waiting_for_flow"]       = True
                        cycle_paused = False
                        cycle_active = False

                with self._state_lock:
                    self._state["flow_check_q"]  = round(fs.flow_l_min, 1)
                    self._state["flow_threshold"] = round(flow_thr, 1)

                if cycle_paused:
                    if self._display:
                        pause_secs = now_ts - (self._state.get("cycle_pause_start_time") or now_ts)
                        self._display.show_cycle_paused(
                            self._state.get("cycle_active_seconds", 0.0), pause_secs
                        )
                    with self._state_lock:
                        self._state["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    time.sleep(interval)
                    continue

            elif not sim_mode and cycle_active and not awaiting and not sensor_error:
                # Zyklus aktiv – Betriebszeit zählen und Pause prüfen
                if flow_ok:
                    self.mstate.flow_below_since = None
                    with self._state_lock:
                        self._state["cycle_active_seconds"] = (
                            self._state.get("cycle_active_seconds", 0.0) + interval
                        )
                else:
                    if self.mstate.flow_below_since is None:
                        self.mstate.flow_below_since = now_ts
                    elif now_ts - self.mstate.flow_below_since >= pause_tol:
                        # Zyklus pausieren
                        op_label = "Batch-Pause" if self._settings.get("operation_mode") == "batch" else "Unterbrechung"
                        self._learning.add_event("PAUSE_START",
                                           f"{op_label} gestartet – Q={fs.flow_l_min:.1f} l/min",
                                           category="pause")
                        self._db.insert_service_event("ZYKLUS_PAUSE_START", heta_code,
                                                f"Q={fs.flow_l_min:.1f} l/min unter Schwellwert {flow_thr:.1f} l/min")
                        self.mstate.flow_below_since  = None
                        self.mstate.flow_stable_since = None
                        with self._state_lock:
                            self._state["cycle_paused"]           = True
                            self._state["cycle_pause_start_time"] = now_ts
                        cycle_paused = True
                        logger.info("Zyklus pausiert – Q=%.1f l/min < Schwellwert %.1f l/min.",
                                    fs.flow_l_min, flow_thr)

            elif not cycle_active and not waiting_for_flow and not cycle_paused and not awaiting:
                # Kein Zyklus und nicht wartend → in waiting_for_flow gehen
                with self._state_lock:
                    self._state["waiting_for_flow"] = True
                waiting_for_flow = True

            # ── Kurvenbasierter Profilvergleich ───────────────────────────────
            with self._state_lock:
                cycle_start_ts    = self._state.get("cycle_start_time")
                cycle_active_secs = self._state.get("cycle_active_seconds", 0.0)
            elapsed = cycle_active_secs if cycle_active_secs > 0 else (
                (now_ts - cycle_start_ts) if cycle_start_ts else 0.0
            )

            an_active = profile_valid and heta_activated and not sensor_error
            an_ready  = False
            analysis  = None
            cycle_progress_pct = 0.0
            analysis_elapsed   = 0.0
            dp_slope_ref   = dp_slope_cur   = dp_dev   = 0.0
            flow_slope_ref = flow_slope_cur = flow_dev = 0.0
            temp_slope_ref = temp_slope_cur = temp_dev = 0.0
            reff_slope_ref = reff_slope_cur = reff_dev = 0.0

            # ── Kanalsteigungen und dp-History aktualisieren (vor Kurvenanalyse) ─
            # Reihenfolge wichtig: erst update → dann get_current_slope(),
            # damit die Analyse den aktuellen Messwert enthält.
            self._predictor.update_channels(fs.flow_l_min, fs.temperature_c, fs.r_eff)

            # ── Reststandzeit berechnen ───────────────────────────────────────
            # Bei validiertem Profil: Referenzkurve invertieren → passt sich sofort
            # an reduzierte/erhöhte Schmutzfracht an (kein sek.-weiser Countdown).
            # Ohne valides Profil: dp-Steigung (Seeded-Ceiling-Fallback).
            if profile_valid and profile:
                _rc_json = profile.get("reference_curve_json")
                _rc_dur  = profile.get("reference_duration_seconds", 0.0)
                if _rc_json and _rc_dur > 0:
                    try:
                        _rc = json.loads(_rc_json) if isinstance(_rc_json, str) else _rc_json
                        remaining_s = self._predictor.update_with_reference_curve(
                            fs.dp_bar, _rc_dur, _rc, elapsed
                        )
                    except Exception as _e:
                        logger.warning("update_with_reference_curve Fehler: %s", _e)
                        remaining_s = self._predictor.update(fs.dp_bar)
                else:
                    remaining_s = self._predictor.update(fs.dp_bar)
            else:
                remaining_s = self._predictor.update(fs.dp_bar)

            # ── Kurvenbasierter Profilvergleich (nach dp-Update, Steigungen frisch) ─
            if an_active and cycle_active:
                try:
                    ch_slopes = self._predictor.get_channel_slopes()
                    analysis = self._learning.get_curve_analysis(
                        heta_code, elapsed,
                        fs.dp_bar, fs.r_eff, fs.flow_l_min, fs.temperature_c,
                        current_dp_slope=self._predictor.get_current_slope(),
                        current_flow_slope=ch_slopes["flow"],
                        current_temp_slope=ch_slopes["temp"],
                        current_reff_slope=ch_slopes["r_eff"],
                    )
                except Exception as _e:
                    logger.warning("Kurvenanalyse-Fehler: %s", _e, exc_info=True)
                    analysis = None
                if analysis:
                    an_ready           = True
                    cycle_progress_pct = analysis["cycle_progress_pct"]
                    analysis_elapsed   = analysis["elapsed_seconds"]
                    dp_slope_ref       = analysis["ref_dp_slope"]
                    dp_slope_cur       = analysis["cur_dp_slope"]   or 0.0
                    dp_dev             = analysis["dp_deviation_pct"]
                    flow_slope_ref     = analysis["ref_flow_slope"]
                    flow_slope_cur     = analysis["cur_flow_slope"]  or 0.0
                    flow_dev           = analysis["flow_deviation_pct"]
                    temp_slope_ref     = analysis["ref_temp_slope"]
                    temp_slope_cur     = analysis["cur_temp_slope"]  or 0.0
                    temp_dev           = analysis["temp_deviation_pct"]
                    reff_slope_ref     = analysis["ref_reff_slope"]
                    reff_slope_cur     = analysis["cur_reff_slope"]  or 0.0
                    reff_dev           = analysis["r_eff_deviation_pct"]

            # ── Lernwert erfassen (mit Beladungsgrad und Reststandzeit) ───────
            if cycle_active and not sensor_error:
                self._learning.record_sample(
                    fs.flow_l_min, fs.temperature_c, fs.dp_bar, fs.r_eff,
                    p1=fs.p1_bar, p2=fs.p2_bar, timestamp=time.time(),
                    filter_health_percent=smoothed_health,
                    remaining_seconds=remaining_s,
                )

            # ── Startverhalten prüfen (erste 10 Sekunden) ────────────────────
            if (cycle_active and heta_activated and cycle_start_ts
                    and (time.time() - cycle_start_ts) < 10):
                anomaly, anom_pct = self._learning.check_start_behavior(heta_code, fs.r_eff)
                # Atomar lesen + schreiben unter self._state_lock; learning-Calls danach.
                with self._state_lock:
                    was_anomaly = self._state["anomaly_active"]
                    self._state["anomaly_active"] = anomaly
                    self._state["anomaly_percent"] = anom_pct
                if anomaly and not was_anomaly:
                    self._learning.add_event("WARNUNG",
                        f"Startverhalten-Anomalie: R_eff {anom_pct:+.1f}% zur Referenz",
                        category="anomaly")
                elif not anomaly and was_anomaly:
                    self._learning.close_event(category="anomaly")
            elif cycle_active:
                # Fenster abgelaufen – Anomalie ggf. einmalig schließen.
                with self._state_lock:
                    close_anomaly = self._state["anomaly_active"]
                    if close_anomaly:
                        self._state["anomaly_active"] = False
                        self._state["anomaly_percent"] = 0.0
                if close_anomaly:
                    self._learning.close_event(category="anomaly")

            # ── Statusänderungen als Ereignis im aktiven Zyklus speichern ────
            prev_status = self._state.get("filter_status", STATUS_OK)
            if fs.status != prev_status and cycle_active:
                if fs.status == STATUS_FEHLER:
                    self._learning.add_event("FEHLER", "Sensorfehler erkannt", category="status")
                elif fs.status == STATUS_WARNUNG:
                    self._learning.add_event("WARNUNG", "Anomales Beladungsverhalten erkannt", category="status")
                elif fs.status in (STATUS_WECHSEL, STATUS_WECHSEL_BESTAETIGEN):
                    self._learning.add_event("WECHSEL",
                        f"Filterwechsel erforderlich – Δp={fs.dp_bar:.3f} bar", category="status")
                elif prev_status in (STATUS_FEHLER, STATUS_WARNUNG) and fs.status == STATUS_OK:
                    self._learning.close_event(category="status")

            # ── Abweichungs-Perioden tracken (Δp, Q, R_eff) ─────────────────
            if cycle_active and an_ready and profile_valid:
                tol_dp   = self._settings.get("tolerance_dp_pct",   0.25) * 100
                tol_flow = self._settings.get("tolerance_flow_pct", 0.25) * 100
                tol_reff = self._settings.get("tolerance_reff_pct", 0.25) * 100
                checks = [
                    ("dp",   dp_dev,   tol_dp,   f"Δp-Abweichung: +{dp_dev:.0f}% zur Referenz"),
                    ("flow", flow_dev, tol_flow, f"Durchfluss-Abweichung: {flow_dev:.0f}% zur Referenz"),
                    ("reff", reff_dev, tol_reff, f"Filterwiderstand-Abweichung: +{reff_dev:.0f}% zur Referenz"),
                ]
                # Read-Modify-Write atomar unter self._state_lock – verhindert Race mit
                # API-Handlern (Filterwechsel, Reset), die _dev_active zurücksetzen.
                with self._state_lock:
                    dev_active = self._state.get("_dev_active", {"dp": False, "flow": False, "reff": False})
                    for ch, dev, tol, msg in checks:
                        exceeds = abs(dev) > tol
                        was_active = dev_active.get(ch, False)
                        if exceeds and not was_active:
                            self._learning.add_event("ABWEICHUNG", msg, category=f"dev_{ch}")
                            dev_active[ch] = True
                        elif not exceeds and was_active:
                            self._learning.close_event(category=f"dev_{ch}")
                            dev_active[ch] = False
                    self._state["_dev_active"] = dev_active

            # ── Prognosestatus ────────────────────────────────────────────────
            req_cycles  = self._settings.get("required_cycles_for_profile", 3)
            pred_status = self._predictor.get_status(
                remaining_seconds=remaining_s,
                heta_activated=heta_activated,
                profile_valid=profile_valid,
                learned_cycles=cycles_count,
                required_cycles=req_cycles,
            )

            # ── Filterwechsel erkennen ────────────────────────────────────────
            if fs.dp_bar >= dp_limit and not awaiting and cycle_active:
                logger.warning("Filterwechsel-Grenzwert überschritten! dp=%.3f >= %.2f",
                               fs.dp_bar, dp_limit)
                with self._state_lock:
                    self._state["awaiting_confirmation"]  = True
                    self._state["cycle_dp_reached_time"]  = time.time()
                if self._display_ctrl:
                    self._display_ctrl.navigate_to_filter_change()
                    self._display.show_filter_change(fs.dp_bar, dp_limit, armed=False, awaiting=True)
                elif self._display:
                    self._display.show_filter_change(fs.dp_bar, dp_limit, armed=False, awaiting=True)
                if self._services.get("mqtt"):
                    self._services.get("mqtt").publish_alarm("WECHSEL", "Filterwechsel erforderlich!", heta_code)

            # ── Serviceempfehlung ─────────────────────────────────────────────
            rec = self._generate_service_rec(fs, pred_status, health_percent=smoothed_health)

            # ── Datenbank ─────────────────────────────────────────────────────
            self._db.insert_measurement({
                "timestamp": time.time(),
                "p1_bar": fs.p1_bar,
                "p2_bar": fs.p2_bar,
                "dp_bar": fs.dp_bar,
                "flow_l_min": fs.flow_l_min,
                "temperature_c": fs.temperature_c,
                "r_eff": fs.r_eff,
                "filter_health_percent": smoothed_health,
                "status": fs.status,
                "heta_code": heta_code,
                "sensor_mode": sensor_mode,
            })

            # ── dp-Puffer aktualisieren (Fallback-Prognose) ───────────────────
            self._dp_rate_buffer.append((time.time(), fs.dp_bar))

            with self._state_lock:
                self._state.update({
                    "analysis_active":              an_active,
                    "analysis_ready":               an_ready,
                    "analysis_cycle_progress_pct":  cycle_progress_pct,
                    "analysis_elapsed_seconds":     analysis_elapsed,
                    "analysis_dp_rate_ref":         dp_slope_ref,
                    "analysis_dp_rate_current":     dp_slope_cur,
                    "analysis_dp_deviation_pct":    dp_dev,
                    "analysis_flow_rate_ref":       flow_slope_ref,
                    "analysis_flow_rate_current":   flow_slope_cur,
                    "analysis_flow_deviation_pct":  flow_dev,
                    "analysis_temp_rate_ref":       temp_slope_ref,
                    "analysis_temp_rate_current":   temp_slope_cur,
                    "analysis_temp_deviation_pct":  temp_dev,
                    "analysis_reff_rate_ref":       reff_slope_ref,
                    "analysis_reff_rate_current":   reff_slope_cur,
                    "analysis_reff_deviation_pct":  reff_dev,
                })

            # MQTT
            if self._services.get("mqtt") and self._services.get("mqtt").is_connected:
                self._services.get("mqtt").publish_measurements(fs, heta_code)

            # Modbus TCP
            if self._services.get("modbus") and self._services.get("modbus").is_running:
                self._services.get("modbus").update(fs, self._state)

            # Display aktualisieren
            _status_display_data = {
                "heta_code":   heta_code or "---",
                "mode":        "SIM" if sim_mode else "HW",
                "p1":          fs.p1_bar,
                "p2":          fs.p2_bar,
                "dp":          fs.dp_bar,
                "dp_limit":    dp_limit,
                "flow":        fs.flow_l_min,
                "temperature": fs.temperature_c,
                "remaining":   pred_status["remaining_display"],
                "status":      fs.status,
            }
            if self._display_ctrl:
                self._display_ctrl.update_status(_status_display_data)
            elif self._display:
                self._display.show_status(_status_display_data)

            # Systemzustand aktualisieren
            with self._state_lock:
                self._state.update({
                    "sensor_mode": sensor_mode,
                    "p1_bar": fs.p1_bar,
                    "p2_bar": fs.p2_bar,
                    "dp_bar": fs.dp_bar,
                    "flow_l_min": fs.flow_l_min,
                    "temperature_c": fs.temperature_c,
                    "r_eff": fs.r_eff,
                    "r_rel_factor": round(fs.r_eff / r_eff_clean_ref, 4) if (r_eff_clean_ref and r_eff_clean_ref > 0) else None,
                    "filter_health_percent": smoothed_health,
                    "filter_status": fs.status,
                    "sensor_error": fs.sensor_error,
                    "remaining_display": pred_status["remaining_display"],
                    "remaining_seconds": pred_status["remaining_seconds"],
                    "prediction_mode": pred_status["prediction_mode"],
                    "learned_cycles": cycles_count,
                    "required_cycles": req_cycles,
                    "profile_status": "VALIDIERT" if profile_valid else "LERNEND",
                    "reference_dp_clean": (_loop_profile.get("reference_dp_clean") or 0.0) if _loop_profile else 0.0,
                    "show_filter_health": heta_activated,
                    "service_message": rec["message"],
                    "service_priority": rec["priority"],
                    "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "sim_rates_active": self._get_sim_rates(),
                    "sim_estimated_cycle_secs": round(self._get_sim_cycle_secs(), 1),
                    "operation_mode": self._settings.get("operation_mode", "continuous"),
                })

            loop_elapsed = time.time() - t_start
            sleep_time = max(0.0, interval - loop_elapsed)
            time.sleep(sleep_time)

        logger.info("Messzyklus beendet.")

    def confirm_filter_change(self):
        """Filterwechsel bestätigen (ehemals _do_confirm_filter_change in app.py)."""
        with self._state_lock:
            heta_code        = self._state["heta_code"]
            cycle_was_active = self._state["cycle_active"]
            active_secs      = self._state.get("cycle_active_seconds", 0.0)

        if cycle_was_active and self._learning.active_cycle:
            with self._state_lock:
                current_r        = self._state["r_eff"]
                current_dp       = self._state["dp_bar"]
                dp_reached_time  = self._state.get("cycle_dp_reached_time")
            # Auto-Schwellwerte aus Zyklus-Samples aktualisieren
            if heta_code:
                try:
                    samples = [{"dp_bar": s, "flow_l_min": f}
                               for s, f in zip(
                                   self._learning.active_cycle.dp_samples,
                                   self._learning.active_cycle.flow_samples,
                               )]
                    self._update_auto_thresholds(samples)
                except Exception:
                    pass
            self._learning.end_cycle(confirmed=True,
                               end_r_eff=current_r,
                               end_dp=current_dp,
                               end_time=dp_reached_time,
                               active_seconds=active_secs if active_secs > 0 else None)

        self.mstate.smoothed_health_pct = None
        self._predictor.reset()
        self._dp_rate_buffer.clear()
        self.mstate.flow_stable_since = None
        self.mstate.flow_below_since  = None
        self._reset_simulation()

        with self._state_lock:
            self._state["awaiting_confirmation"]  = False
            self._state["cycle_active"]           = False
            self._state["cycle_paused"]           = False
            self._state["waiting_for_flow"]       = True   # Warten auf Durchfluss nach Wechsel
            self._state["cycle_start_time"]       = None
            self._state["cycle_dp_reached_time"]  = None
            self._state["cycle_active_seconds"]   = 0.0
            self._state["cycle_pause_start_time"] = None
            self._state["anomaly_active"]        = False
            self._state["_dev_active"]          = {"dp": False, "flow": False, "reff": False}
            self._state["anomaly_percent"]        = 0.0

        self._db.insert_service_event("FILTERWECHSEL_BESTAETIGT", heta_code,
                                json.dumps({"timestamp": time.time()}))
        logger.info("Filterwechsel bestätigt – warte auf Durchfluss für neuen Zyklus.")
