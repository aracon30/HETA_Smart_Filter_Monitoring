"""
Datenbankmodul – SQLite-Datenbank für Messwerte, Filterzyklen, Profile und Serviceereignisse.
"""

import sqlite3
import os
import csv
import logging
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    """Verwaltet alle Datenbankoperationen über eine SQLite-Datei."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        """Kontextmanager für Datenbankverbindungen mit automatischem Commit/Rollback."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Erstellt alle Tabellen falls noch nicht vorhanden."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS measurements (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   REAL    NOT NULL,
                    p1_bar      REAL,
                    p2_bar      REAL,
                    dp_bar      REAL,
                    flow_l_min  REAL,
                    temperature_c REAL,
                    r_eff       REAL,
                    filter_health_percent REAL,
                    status      TEXT,
                    heta_code   TEXT,
                    sensor_mode TEXT
                );

                CREATE TABLE IF NOT EXISTS filter_cycles (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    heta_code           TEXT,
                    start_time          REAL,
                    end_time            REAL,
                    duration_seconds    REAL,
                    start_r_eff         REAL,
                    end_r_eff           REAL,
                    start_dp            REAL,
                    end_dp              REAL,
                    average_flow        REAL,
                    average_temperature REAL,
                    loading_rate        REAL,
                    confirmed_filter_change INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS heta_profiles (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    heta_code       TEXT UNIQUE,
                    reference_r_eff REAL,
                    reference_loading_rate REAL,
                    cycles_count    INTEGER DEFAULT 0,
                    profile_valid   INTEGER DEFAULT 0,
                    last_updated    REAL
                );

                CREATE TABLE IF NOT EXISTS service_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   REAL    NOT NULL,
                    event_type  TEXT,
                    heta_code   TEXT,
                    payload     TEXT
                );

                CREATE TABLE IF NOT EXISTS cycle_samples (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_id              INTEGER NOT NULL,
                    heta_code             TEXT    NOT NULL,
                    timestamp             REAL    NOT NULL,
                    cycle_second          REAL    NOT NULL,
                    p1_bar                REAL,
                    p2_bar                REAL,
                    dp_bar                REAL,
                    flow_l_min            REAL,
                    temp_c                REAL,
                    r_eff                 REAL,
                    filter_health_percent REAL,
                    remaining_seconds     REAL
                );
                CREATE INDEX IF NOT EXISTS idx_cs_cycle ON cycle_samples(cycle_id);
                CREATE INDEX IF NOT EXISTS idx_cs_heta  ON cycle_samples(heta_code);
            """)
        logger.info("Datenbank initialisiert: %s", self.db_path)

        # Schema-Migration: neue heta_profiles-Spalten
        with self._conn() as conn:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(heta_profiles)").fetchall()}
            for col, typ, default in [
                ("reference_avg_flow",         "REAL", "0.0"),
                ("reference_avg_temp",         "REAL", "20.0"),
                ("reference_curve_json",       "TEXT", "NULL"),
                ("reference_duration_seconds", "REAL", "0.0"),
                ("reference_r_eff_start",      "REAL", "0.0"),
                ("reference_r_eff_end",        "REAL", "0.0"),
            ]:
                if col not in existing:
                    conn.execute(f"ALTER TABLE heta_profiles ADD COLUMN {col} {typ} DEFAULT {default}")

        # Schema-Migration: neue cycle_samples-Spalten
        with self._conn() as conn:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(cycle_samples)").fetchall()}
            for col, typ, default in [
                ("filter_health_percent", "REAL", "NULL"),
                ("remaining_seconds",     "REAL", "NULL"),
            ]:
                if col not in existing:
                    conn.execute(f"ALTER TABLE cycle_samples ADD COLUMN {col} {typ} DEFAULT {default}")

        # Schema-Migration: events_json in filter_cycles
        with self._conn() as conn:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(filter_cycles)").fetchall()}
            if "events_json" not in existing:
                conn.execute("ALTER TABLE filter_cycles ADD COLUMN events_json TEXT DEFAULT '[]'")

    # ------------------------------------------------------------------
    # Messwerte
    # ------------------------------------------------------------------

    def insert_measurement(self, data: dict) -> int:
        """Speichert einen Messwert und gibt die neue ID zurück."""
        sql = """
            INSERT INTO measurements
                (timestamp, p1_bar, p2_bar, dp_bar, flow_l_min, temperature_c,
                 r_eff, filter_health_percent, status, heta_code, sensor_mode)
            VALUES
                (:timestamp, :p1_bar, :p2_bar, :dp_bar, :flow_l_min, :temperature_c,
                 :r_eff, :filter_health_percent, :status, :heta_code, :sensor_mode)
        """
        with self._conn() as conn:
            cur = conn.execute(sql, data)
            return cur.lastrowid

    def get_latest_measurements(self, limit: int = 100) -> list:
        """Gibt die letzten N Messwerte zurück."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM measurements ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_measurements_since(self, since_timestamp: float) -> list:
        """Gibt alle Messwerte seit einem bestimmten Zeitstempel zurück."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM measurements WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since_timestamp,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Filterzyklen
    # ------------------------------------------------------------------

    def insert_cycle(self, data: dict) -> int:
        """Speichert einen abgeschlossenen Filterzyklus."""
        data.setdefault("events_json", "[]")
        sql = """
            INSERT INTO filter_cycles
                (heta_code, start_time, end_time, duration_seconds,
                 start_r_eff, end_r_eff, start_dp, end_dp,
                 average_flow, average_temperature, loading_rate, confirmed_filter_change,
                 events_json)
            VALUES
                (:heta_code, :start_time, :end_time, :duration_seconds,
                 :start_r_eff, :end_r_eff, :start_dp, :end_dp,
                 :average_flow, :average_temperature, :loading_rate, :confirmed_filter_change,
                 :events_json)
        """
        with self._conn() as conn:
            cur = conn.execute(sql, data)
            return cur.lastrowid

    def insert_cycle_samples(self, samples: list) -> None:
        """Speichert die Zeitreihen-Messwerte eines Filterzyklus (Bulk-Insert)."""
        if not samples:
            return
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO cycle_samples
                   (cycle_id, heta_code, timestamp, cycle_second,
                    p1_bar, p2_bar, dp_bar, flow_l_min, temp_c, r_eff,
                    filter_health_percent, remaining_seconds)
                   VALUES
                   (:cycle_id, :heta_code, :timestamp, :cycle_second,
                    :p1_bar, :p2_bar, :dp_bar, :flow_l_min, :temp_c, :r_eff,
                    :filter_health_percent, :remaining_seconds)""",
                samples,
            )

    def get_cycle_samples(self, cycle_id: int) -> list:
        """Gibt alle Messwerte eines bestimmten Filterzyklus zurück."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cycle_samples WHERE cycle_id = ? ORDER BY cycle_second ASC",
                (cycle_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_cycles_for_heta(self, heta_code: str) -> list:
        """Gibt alle Filterzyklen für einen HETA-Code zurück."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM filter_cycles WHERE heta_code = ? ORDER BY start_time ASC",
                (heta_code,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_confirmed_cycles(self, heta_code: str) -> int:
        """Zählt bestätigte Filterzyklen für einen HETA-Code."""
        with self._conn() as conn:
            result = conn.execute(
                "SELECT COUNT(*) FROM filter_cycles WHERE heta_code = ? AND confirmed_filter_change = 1",
                (heta_code,),
            ).fetchone()
        return result[0] if result else 0

    def get_recent_cycles(self, limit: int = 4) -> list:
        """Gibt die letzten N Filterzyklen zurück (alle HETA-Codes)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM filter_cycles ORDER BY end_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # HETA-Profile
    # ------------------------------------------------------------------

    def upsert_profile(self, heta_code: str, data: dict):
        """Erstellt oder aktualisiert ein HETA-Profil."""
        data["heta_code"] = heta_code
        data.setdefault("last_updated", time.time())
        data.setdefault("reference_curve_json", None)
        data.setdefault("reference_duration_seconds", 0.0)
        data.setdefault("reference_r_eff_start", 0.0)
        data.setdefault("reference_r_eff_end", 0.0)
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO heta_profiles
                    (heta_code, reference_r_eff, reference_loading_rate,
                     reference_avg_flow, reference_avg_temp,
                     reference_curve_json, reference_duration_seconds,
                     reference_r_eff_start, reference_r_eff_end,
                     cycles_count, profile_valid, last_updated)
                VALUES
                    (:heta_code, :reference_r_eff, :reference_loading_rate,
                     :reference_avg_flow, :reference_avg_temp,
                     :reference_curve_json, :reference_duration_seconds,
                     :reference_r_eff_start, :reference_r_eff_end,
                     :cycles_count, :profile_valid, :last_updated)
                ON CONFLICT(heta_code) DO UPDATE SET
                    reference_r_eff              = excluded.reference_r_eff,
                    reference_loading_rate       = excluded.reference_loading_rate,
                    reference_avg_flow           = excluded.reference_avg_flow,
                    reference_avg_temp           = excluded.reference_avg_temp,
                    reference_curve_json         = excluded.reference_curve_json,
                    reference_duration_seconds   = excluded.reference_duration_seconds,
                    reference_r_eff_start        = excluded.reference_r_eff_start,
                    reference_r_eff_end          = excluded.reference_r_eff_end,
                    cycles_count                 = excluded.cycles_count,
                    profile_valid                = excluded.profile_valid,
                    last_updated                 = excluded.last_updated
            """, data)

    def get_profile(self, heta_code: str) -> Optional[dict]:
        """Gibt das gespeicherte HETA-Profil zurück oder None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM heta_profiles WHERE heta_code = ?", (heta_code,)
            ).fetchone()
        return dict(row) if row else None

    def reset_cycles_for_heta(self, heta_code: str):
        """Löscht alle Zyklen, Sample-Zeitreihen und das Profil für einen einzelnen HETA-Code."""
        with self._conn() as conn:
            conn.execute("DELETE FROM cycle_samples WHERE heta_code = ?", (heta_code,))
            conn.execute("DELETE FROM filter_cycles   WHERE heta_code = ?", (heta_code,))
            conn.execute("DELETE FROM heta_profiles   WHERE heta_code = ?", (heta_code,))
        logger.info("Lernzyklen, Sample-Zeitreihen und Profil für %s zurückgesetzt.", heta_code)

    def reset_all_learning_data(self):
        """
        Löscht alle Lernzyklen, Sample-Zeitreihen und Profile.
        Wird aufgerufen wenn kritische Konfigurationsparameter geändert werden,
        damit die 3 Lernphasen sauber neu durchlaufen werden.
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM cycle_samples")
            conn.execute("DELETE FROM filter_cycles")
            conn.execute("DELETE FROM heta_profiles")
        logger.info("Alle Lerndaten, Sample-Zeitreihen und Profile gelöscht (Neukonfiguration).")

    def wipe_all_data(self):
        """Löscht alle Tabellen vollständig – für Werksreset."""
        with self._conn() as conn:
            conn.execute("DELETE FROM cycle_samples")
            conn.execute("DELETE FROM filter_cycles")
            conn.execute("DELETE FROM heta_profiles")
            conn.execute("DELETE FROM service_events")
        logger.info("Alle Daten in der Datenbank gelöscht (Werksreset).")

    # ------------------------------------------------------------------
    # Serviceereignisse
    # ------------------------------------------------------------------

    def insert_service_event(self, event_type: str, heta_code: str, payload: str):
        """Speichert ein Serviceereignis."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO service_events (timestamp, event_type, heta_code, payload) VALUES (?, ?, ?, ?)",
                (time.time(), event_type, heta_code, payload),
            )

    def get_service_events(self, limit: int = 50) -> list:
        """Gibt die letzten Serviceereignisse zurück."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM service_events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # CSV-Export
    # ------------------------------------------------------------------

    def export_measurements_csv(self, filepath: str, since_timestamp: float = 0.0) -> int:
        """
        Exportiert Messwerte als CSV-Datei.
        Gibt die Anzahl exportierter Zeilen zurück.
        """
        rows = self.get_measurements_since(since_timestamp)
        if not rows:
            return 0
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        fieldnames = list(rows[0].keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        logger.info("CSV-Export: %d Zeilen nach %s", len(rows), filepath)
        return len(rows)
