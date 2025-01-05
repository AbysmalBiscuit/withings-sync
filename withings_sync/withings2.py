#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.parse
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from pprint import pformat
from typing import TYPE_CHECKING, ClassVar, Literal, TypeAlias, TypedDict, cast

import requests

from withings_sync.get_logger import get_logger

if TYPE_CHECKING:
    from verboselogs import VerboseLogger

logger: VerboseLogger = get_logger(__name__)


class WithingsError(Exception):
    pass


class ConfigDict(TypedDict):
    callback_url: str
    client_id: str
    consumer_secret: str
    access_token: str
    authentification_code: str
    refresh_token: str
    userid: str
    last_update_garmin: int | None
    last_update_trainerroad: int | None


class PartialConfigDict(ConfigDict, total=False):
    pass


ConfigKeys: TypeAlias = Literal[
    "callback_url",
    "client_id",
    "consumer_secret",
    "access_token",
    "authentification_code",
    "refresh_token",
    "userid",
    "last_update_garmin",
    "last_update_trainerroad",
]


class WithingsConfig:
    HOME: Path = Path.home()
    AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
    TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
    GETMEAS_URL = "https://wbsapi.withings.net/measure?action=getmeas"

    _config: ConfigDict = cast(ConfigDict, {})
    _config_file: Path = HOME.joinpath(".config/withings-sync/config.json")

    _config_template: ClassVar[ConfigDict] = {
        "callback_url": "https://jaroslawhartman.github.io/withings-sync/contrib/withings.html",
        "client_id": "183e03e1f363110b3551f96765c98c10e8f1aa647a37067a1cb64bbbaf491626",
        "consumer_secret": "a75d655c985d9e6391df1514c16719ef7bd69fa7c5d3fd0eac2e2b0ed48f1765",
        "access_token": "",
        "authentification_code": "",
        "refresh_token": "",
        "userid": "",
        "last_update_garmin": None,
        "last_update_trainerroad": None,
    }

    def __init__(self, config_file: Path | None = None) -> None:
        if config_file is not None:
            self.__class__.config_file = Path(config_file)

        if not self.config_file.parent.is_dir():
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.config_file.is_file():
            self.config = deepcopy(self.__class__._config_template)
            self.save()
        else:
            self.load()

            # Check to make sure config matches current template
            if self.config.keys() != self.__class__._config_template.keys():
                merged_config: ConfigDict = deepcopy(self.__class__._config_template)
                merged_config.update(self.config)
                self.config = merged_config
                self.save()

    @property
    def config_file(self) -> Path:
        return self.__class__._config_file

    @config_file.setter
    def config_file(self, value: Path) -> None:
        assert isinstance(value, Path)
        self.__class__.config_file = value

    @property
    def config(self) -> ConfigDict:
        return self.__class__._config

    @config.setter
    def config(self, value: ConfigDict) -> None:
        assert isinstance(value, dict)
        self.__class__._config = value

    def __contains__(self, item: ConfigKeys) -> bool:
        return item in self.__class__._config

    def __getitem__(self, item: ConfigKeys) -> str | int | None:
        return self.__class__._config[item]

    def __setitem__(self, key: ConfigKeys, value: str | int | None) -> None:
        self.__class__._config[key] = value

    def __str__(self) -> str:
        return str(self.config)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(config_file={self.config_file})"

    def get(self, item: ConfigKeys, default: str | int | None = None) -> str | int | datetime | None:
        if item in self.__class__._config:
            return self.__class__._config[item]
        return default

    def load(self, config_file: Path | None = None) -> None:
        config_file = config_file or self.config_file
        try:
            with open(config_file) as f:
                self.config = json.load(f)
        except (ValueError, FileNotFoundError):
            logger.exception(f"Cannot load config file {config_file}")
            self.config = cast(ConfigDict, {})

    def save(self) -> None:
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=2, sort_keys=True)

    def reset(self) -> None:
        self.config = deepcopy(self.__class__._config_template)
        self.save()


class WithingsOAuth2:
    def __init__(self, config: WithingsConfig) -> None:
        self.config: WithingsConfig = config

        if self.config.get("access_token") is None or len(self.config.get("access_token", "")) == 0:
            if (
                self.config.get("authentification_code") is None
                or len(self.config.get("authentification_code", "")) == 0
            ):
                self.config["authentification_code"] = self.get_authentication_code()

            self.get_access_token()

        self.refresh_access_token()

    def get_authentication_code(self) -> str:
        params: dict[str, str | int | None] = {
            "response_type": "code",
            "client_id": self.config["client_id"],
            "state": "OK",
            "scope": "user.metrics",
            "redirect_uri": self.config["callback_url"],
        }
        logger.debug(params)

        logger.warning("User interaction needed to get Authentification Code from Withings!")
        logger.warning(
            "Open the following URL in your web browser and copy back "
            "the token. You will have *30 seconds* before the "
            "token expires. HURRY UP!"
        )
        logger.warning("(This is one-time activity)")

        url = WithingsConfig.AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

        # for key, value in params.items():
        #     url = url + key + "=" + value + "&"

        logger.info(url)

        authentification_code: str = input("Token : ")

        return authentification_code

    def _update_access_token(self, params: dict[str, str]) -> None:
        req: requests.Response = requests.post(WithingsConfig.TOKEN_URL, params)
        resp = req.json()

        status: int = resp.get("status")
        body = resp.get("body")

        if status != 0:
            error_message: str = f"Received error code: {status}\n"
            error_message += "Check here for an interpretation of this error: "
            error_message += "http://developer.withings.com/api-reference#section/Response-status\n"
            error_message += "If it is regarding an invalid code, try to start the script again to obtain a new link."

            logger.error(error_message)

        self.config["access_token"] = body.get("access_token")
        self.config["refresh_token"] = body.get("refresh_token")
        self.config["userid"] = str(body.get("userid"))
        logger.debug(f"Updated config:\n{pformat(self.config._config)}")

    def get_access_token(self) -> None:
        logger.info("Get Access Token")

        params: PartialConfigDict = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": self.config["client_id"],
            "client_secret": self.config["consumer_secret"],
            "code": self.config["authentification_code"],
            "redirect_uri": self.config["callback_url"],
        }

        self._update_access_token(params)

    def refresh_access_token(self) -> None:
        logger.info("Refresh Access Token")

        params = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.config["client_id"],
            "client_secret": self.config["consumer_secret"],
            "refresh_token": self.config["refresh_token"],
        }

        self._update_access_token(params)


class WithingsAccount:
    def __init__(self, withings_config: WithingsConfig) -> None:
        self.height_group = None
        self.height = None
        self.height_timestamp = None

        self.config = withings_config
        self.oauth = WithingsOAuth2(withings_config)
        self.config.save()

    def get_measurements(self, start_date, end_date) -> list["WithingsMeasureGroup"] | None:
        logger.info("Get Measurements")
        logger.debug(f"Start date: {start_date}, end date: {end_date}")

        params = {
            "access_token": self.config["access_token"],
            # "meastype": Withings.MEASTYPE_WEIGHT,
            "category": 1,
            "startdate": start_date,
            "enddate": end_date,
        }

        req = requests.post(WithingsConfig.GETMEAS_URL, params)

        measurements = req.json()

        if measurements.get("status") == 0:
            logger.debug("Measurements received")

            return [WithingsMeasureGroup(g) for g in measurements.get("body").get("measuregrps")]

    def get_height(self):
        self.height = None
        self.height_timestamp = None
        self.height_group = None

        logger.debug("Get Height")

        params = {
            "access_token": self.oauth.config["access_token"],
            "meastype": WithingsMeasure.TYPE_HEIGHT,
            "category": 1,
        }

        req = requests.post(WithingsConfig.GETMEAS_URL, params)

        measurements = req.json()

        if measurements.get("status") == 0:
            logger.debug("Height received")

            # there could be multiple height records. use the latest one
            for record in measurements.get("body").get("measuregrps"):
                self.height_group = WithingsMeasureGroup(record)
                if self.height is not None:
                    if self.height_timestamp is not None:
                        if self.height_group.get_datetime() > self.height_timestamp:
                            self.height = self.height_group.get_height()
                else:
                    self.height = self.height_group.get_height()
                    self.height_timestamp = self.height_group.get_datetime()

        return self.height


class WithingsMeasureGroup:
    """This class takes care of the group measurement functions"""

    def __init__(self, measuregrp) -> None:
        logger.debug(f"MeasureGroup: {measuregrp}")
        self._raw_data = measuregrp
        self.grpid = measuregrp.get("grpid")
        self.attrib = measuregrp.get("attrib")
        self.date: int = measuregrp.get("date")
        self.category: str = measuregrp.get("category")
        self.measures: list[WithingsMeasure] = [WithingsMeasure(m) for m in measuregrp["measures"]]

    def __iter__(self):
        for measure in self.measures:
            yield measure

    def __len__(self):
        return len(self.measures)

    def get_datetime(self) -> datetime:
        """convenient function to get date & time"""
        return datetime.fromtimestamp(self.date)

    def get_raw_data(self) -> list[WithingsMeasure]:
        """convenient function to get raw data"""
        return self.measures

    def get_weight(self) -> float | None:
        """convenient function to get weight"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_WEIGHT:
                return round(measure.get_value(), 2)
        return None

    def get_height(self) -> float | None:
        """convenient function to get height"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_HEIGHT:
                return round(measure.get_value(), 2)
        return None

    def get_fat_free_mass(self) -> float | None:
        """convenient function to get fat free mass"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_FAT_FREE_MASS:
                return round(measure.get_value(), 2)
        return None

    def get_fat_ratio(self) -> float | None:
        """convenient function to get fat ratio"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_FAT_RATIO:
                return round(measure.get_value(), 2)
        return None

    def get_fat_mass_weight(self):
        """convenient function to get fat mass weight"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_FAT_MASS_WEIGHT:
                return round(measure.get_value(), 2)
        return None

    def get_diastolic_blood_pressure(self) -> float | None:
        """convenient function to get diastolic blood pressure"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_DIASTOLIC_BLOOD_PRESSURE:
                return round(measure.get_value(), 2)
        return None

    def get_systolic_blood_pressure(self) -> float | None:
        """convenient function to get systolic blood pressure"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_SYSTOLIC_BLOOD_PRESSURE:
                return round(measure.get_value(), 2)
        return None

    def get_heart_pulse(self) -> float | None:
        """convenient function to get heart pulse"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_HEART_PULSE:
                return round(measure.get_value(), 2)
        return None

    def get_temperature(self) -> float | None:
        """convenient function to get temperature"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_TEMPERATURE:
                return round(measure.get_value(), 2)
        return None

    def get_sp02(self) -> float | None:
        """convenient function to get sp02"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_SP02:
                return round(measure.get_value(), 2)
        return None

    def get_body_temperature(self) -> float | None:
        """convenient function to get body temperature"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_BODY_TEMPERATURE:
                return round(measure.get_value(), 2)
        return None

    def get_skin_temperature(self) -> float | None:
        """convenient function to get skin temperature"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_SKIN_TEMPERATURE:
                return round(measure.get_value(), 2)
        return None

    def get_muscle_mass(self) -> float | None:
        """convenient function to get muscle mass"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_MUSCLE_MASS:
                return round(measure.get_value(), 2)
        return None

    def get_hydration(self) -> float | None:
        """convenient function to get hydration"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_HYDRATION:
                return round(measure.get_value(), 2)
        return None

    def get_bone_mass(self) -> float | None:
        """convenient function to get bone mass"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_BONE_MASS:
                return round(measure.get_value(), 2)
        return None

    def get_pulse_wave_velocity(self) -> float | None:
        """convenient function to get pulse wave velocity"""
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_PULSE_WAVE_VELOCITY:
                return round(measure.get_value(), 2)
        return None


class WithingsMeasure:
    """This class takes care of the individual measurements"""

    TYPE_WEIGHT = 1
    TYPE_HEIGHT = 4
    TYPE_FAT_FREE_MASS = 5
    TYPE_FAT_RATIO = 6
    TYPE_FAT_MASS_WEIGHT = 8
    TYPE_DIASTOLIC_BLOOD_PRESSURE = 9
    TYPE_SYSTOLIC_BLOOD_PRESSURE = 10
    TYPE_HEART_PULSE = 11
    TYPE_TEMPERATURE = 12
    TYPE_SP02 = 54
    TYPE_BODY_TEMPERATURE = 71
    TYPE_SKIN_TEMPERATURE = 73
    TYPE_MUSCLE_MASS = 76
    TYPE_HYDRATION = 77
    TYPE_BONE_MASS = 88
    TYPE_PULSE_WAVE_VELOCITY = 91
    TYPE_VO2MAX = 123
    TYPE_QRS_INTERVAL = 135
    TYPE_PR_INTERVAL = 136
    TYPE_QT_INTERVAL = 137
    TYPE_CORRECTED_QT_INTERVAL = 138
    TYPE_ATRIAL_FIBRILLATION_PPG = 139
    TYPE_FAT_MASS_SEGMENTS = 174
    TYPE_EXTRACELLULAR_WATER = 168
    TYPE_INTRACELLULAR_WATER = 169
    TYPE_VISCERAL_FAT = 170
    TYPE_MUSCLE_MASS_SEGMENTS = 175
    TYPE_VASCULAR_AGE = 155
    TYPE_ATRIAL_FIBRILLATION = 130
    TYPE_NERVE_HEALTH_LEFT_FOOT = 158
    TYPE_NERVE_HEALTH_RIGHT_FOOT = 159
    TYPE_NERVE_HEALTH_FEET = 167
    TYPE_ELECTRODERMAL_ACTIVITY_FEET = 196
    TYPE_ELECTRODERMAL_ACTIVITY_LEFT_FOOT = 197
    TYPE_ELECTRODERMAL_ACTIVITY_RIGHT_FOOT = 198

    withings_table: dict[int, list[str]] = {
        TYPE_WEIGHT: ["Weight", "kg"],
        TYPE_HEIGHT: ["Height", "meter"],
        TYPE_FAT_FREE_MASS: ["Fat Free Mass", "kg"],
        TYPE_FAT_RATIO: ["Fat Ratio", "%"],
        TYPE_FAT_MASS_WEIGHT: ["Fat Mass Weight", "kg"],
        TYPE_DIASTOLIC_BLOOD_PRESSURE: ["Diastolic Blood Pressure", "mmHg"],
        TYPE_SYSTOLIC_BLOOD_PRESSURE: ["Systolic Blood Pressure", "mmHg"],
        TYPE_HEART_PULSE: ["Heart Pulse", "bpm"],
        TYPE_TEMPERATURE: ["Temperature", "celsius"],
        TYPE_SP02: ["SP02", "%"],
        TYPE_BODY_TEMPERATURE: ["Body Temperature", "celsius"],
        TYPE_SKIN_TEMPERATURE: ["Skin Temperature", "celsius"],
        TYPE_MUSCLE_MASS: ["Muscle Mass", "kg"],
        TYPE_HYDRATION: ["Hydration", "kg"],
        TYPE_BONE_MASS: ["Bone Mass", "kg"],
        TYPE_PULSE_WAVE_VELOCITY: ["Pulse Wave Velocity", "m/s"],
        TYPE_VO2MAX: ["VO2 max", "ml/min/kg"],
        TYPE_QRS_INTERVAL: ["QRS interval duration based on ECG signal", "ms"],
        TYPE_PR_INTERVAL: ["PR interval duration based on ECG signal", "ms"],
        TYPE_QT_INTERVAL: ["QT interval duration based on ECG signal", "ms"],
        TYPE_CORRECTED_QT_INTERVAL: [
            "Corrected QT interval duration based on ECG signal",
            "ms",
        ],
        TYPE_ATRIAL_FIBRILLATION_PPG: ["Atrial fibrillation result from PPG", "ms"],
        TYPE_FAT_MASS_SEGMENTS: ["Fat Mass for segments in mass unit", "kg"],
        TYPE_EXTRACELLULAR_WATER: ["Extracellular Water", "kg"],
        TYPE_INTRACELLULAR_WATER: ["Intracellular Water", "kg"],
        TYPE_VISCERAL_FAT: ["Extracellular Water", "kg"],
        TYPE_MUSCLE_MASS_SEGMENTS: ["Muscle Mass for segments in mass unit", "kg"],
        TYPE_VASCULAR_AGE: ["Vascular age", "years"],
        TYPE_ATRIAL_FIBRILLATION: ["Atrial fibrillation result", "ms"],
        TYPE_NERVE_HEALTH_LEFT_FOOT: ["Nerve Health Score left foot", ""],
        TYPE_NERVE_HEALTH_RIGHT_FOOT: ["Nerve Health Score right foot", ""],
        TYPE_NERVE_HEALTH_FEET: ["Nerve Health Score feet", ""],
        TYPE_ELECTRODERMAL_ACTIVITY_FEET: ["Electrodermal activity feet", ""],
        TYPE_ELECTRODERMAL_ACTIVITY_LEFT_FOOT: ["Electrodermal activity left foot", ""],
        TYPE_ELECTRODERMAL_ACTIVITY_RIGHT_FOOT: [
            "Electrodermal activity right foot",
            "",
        ],
    }

    def __init__(self, measure) -> None:
        logger.debug(f"Creating measure: {measure}")
        self._raw_data = measure
        self.value: float = measure.get("value")
        self.type: str = measure.get("type")
        self.unit: str = measure.get("unit")
        self.type_s: str = self.withings_table.get(self.type, ["unknown", ""])[0]
        self.unit_s: str = self.withings_table.get(self.type, ["unknown", ""])[1]

    def __str__(self) -> str:
        return f"{self.type_s}: {self.get_value()} {self.unit_s}"

    def json_dict(self):
        return {
            f"{self.type_s.replace(' ', '_')}": {
                "Value": round(self.get_value(), 2),
                "Unit": f"{self.unit_s}",
            }
        }

    def get_value(self) -> float:
        """get value"""
        return self.value * pow(10, self.unit)
