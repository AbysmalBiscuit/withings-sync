#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
from pathlib import Path
from typing import Union

import requests
import json
import pkg_resources
import os
import sys
from os import PathLike
from datetime import datetime

from .get_logger import get_logger

logger = get_logger(__name__)


class WithingsException(Exception):
    pass


class WithingsConfig:
    HOME = Path.home()
    AUTHORIZE_URL = 'https://account.withings.com/oauth2_user/authorize2'
    TOKEN_URL = 'https://wbsapi.withings.net/v2/oauth2'
    GETMEAS_URL = 'https://wbsapi.withings.net/measure?action=getmeas'

    _config: dict[str, str] = {}
    _config_file: Path = HOME.joinpath('.config/withings-sync/config.json')

    def __init__(self, config_file: PathLike = None):
        if config_file is not None:
            self.__class__.config_file = Path(config_file)

        if not self.config_file.parent.is_dir():
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.config_file.is_file():
            self.config = {
                "callback_url": "https://jaroslawhartman.github.io/withings-sync/contrib/withings.html",
                "client_id": "183e03e1f363110b3551f96765c98c10e8f1aa647a37067a1cb64bbbaf491626",
                "consumer_secret": "a75d655c985d9e6391df1514c16719ef7bd69fa7c5d3fd0eac2e2b0ed48f1765",
                "access_token": "",
                "authentification_code": "",
                "refresh_token": "",
                "userid": "",
                "last_update_garmin": None,
                "last_update_trainerroad": None
            }
            self.save()
        else:
            self.load()

    @property
    def config_file(self):
        return self.__class__._config_file

    @config_file.setter
    def config_file(self, value: Path):
        assert isinstance(value, Path)
        self.__class__.config_file = value

    @property
    def config(self):
        return self.__class__._config

    @config.setter
    def config(self, value: dict):
        assert isinstance(value, dict)
        self.__class__._config = value

    def __contains__(self, item):
        return item in self.__class__._config

    def __getitem__(self, item):
        return self.__class__._config[item]

    def __setitem__(self, key, value):
        self.__class__._config[key] = value

    def __str__(self):
        return str(self.config)

    def __repr__(self):
        return f"{self.__class__.__name__}(config_file={self.config_file})"

    def get(self, item, default=None):
        if item in self.__class__._config:
            return self.__class__._config[item]
        else:
            return default

    def load(self, config_file: PathLike = None):
        config_file = config_file or self.config_file
        try:
            with open(config_file, "r") as f:
                self.config = json.load(f)
        except (ValueError, FileNotFoundError):
            logger.error(f"Can't load config file {config_file}")
            self.config = {}

    def save(self):
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=2, sort_keys=True)


class WithingsOAuth2:
    def __init__(self, config: WithingsConfig):
        self.config = config

        if len(self.config.get('access_token')) == 0:
            if len(self.config.get('authentification_code')):
                self.config['authentification_code'] = self.get_authentication_code()

            self.get_access_token()

        self.refresh_access_token()

    def get_authentication_code(self):
        params = {
            'response_type': 'code',
            'client_id': self.config['client_id'],
            'state': 'OK',
            'scope': 'user.metrics',
            'redirect_uri': self.config['callback_url'],
        }

        logger.warning('User interaction needed to get Authentification '
                 'Code from Withings!')
        logger.warning('')
        logger.warning('Open the following URL in your web browser and copy back '
                 'the token. You will have *30 seconds* before the '
                 'token expires. HURRY UP!')
        logger.warning('(This is one-time activity)')
        logger.warning('')

        url = WithingsConfig.AUTHORIZE_URL + '?'

        for key, value in params.items():
            url = url + key + '=' + value + '&'

        logger.info(url)
        logger.info('')

        authentification_code = input('Token : ')

        return authentification_code

    def _update_access_token(self, params: dict[str, str]):
        req = requests.post(WithingsConfig.TOKEN_URL, params)
        resp = req.json()

        status = resp.get('status')
        body = resp.get('body')

        if status != 0:
            error_message = f"Received error code: {status}\n"
            error_message += "Check here for an interpretation of this error: "
            error_message += "http://developer.withings.com/api-reference#section/Response-status\n"
            error_message += "If it's regarding an invalid code, try to start the script again to obtain a new link."

            logger.error(error_message)

        self.config['access_token'] = body.get('access_token')
        self.config['refresh_token'] = body.get('refresh_token')
        self.config['userid'] = str(body.get('userid'))

    def get_access_token(self):
        logger.info('Get Access Token')

        params = {
            'action': 'requesttoken',
            'grant_type': 'authorization_code',
            'client_id': self.config['client_id'],
            'client_secret': self.config['consumer_secret'],
            'code': self.config['authentification_code'],
            'redirect_uri': self.config['callback_url'],
        }

        self._update_access_token(params)

    def refresh_access_token(self):
        logger.info('Refresh Access Token')

        params = {
            'action': 'requesttoken',
            'grant_type': 'refresh_token',
            'client_id': self.config['client_id'],
            'client_secret': self.config['consumer_secret'],
            'refresh_token': self.config['refresh_token'],
        }

        self._update_access_token(params)


class WithingsAccount:
    def __init__(self, withings_config: WithingsConfig):
        self.height_group = None
        self.height = None
        self.height_timestamp = None

        self.config = withings_config
        self.oauth = WithingsOAuth2(withings_config)
        self.config.save()

    def get_measurements(self, start_date, end_date):
        logger.info('Get Measurements')

        params = {
            'access_token': self.config['access_token'],
            # 'meastype': Withings.MEASTYPE_WEIGHT,
            'category': 1,
            'startdate': start_date,
            'enddate': end_date,
        }

        req = requests.post(WithingsConfig.GETMEAS_URL, params)

        measurements = req.json()

        if measurements.get('status') == 0:
            logger.debug('Measurements received')

            return [WithingsMeasureGroup(g) for
                    g in measurements.get('body').get('measuregrps')]

    def get_height(self):
        self.height = None
        self.height_timestamp = None
        self.height_group = None

        logger.debug('Get Height')

        params = {
            'access_token': self.oauth.config['access_token'],
            'meastype': WithingsMeasure.TYPE_HEIGHT,
            'category': 1,
        }

        req = requests.post(WithingsConfig.GETMEAS_URL, params)

        measurements = req.json()

        if measurements.get('status') == 0:
            logger.debug('Height received')

            # there could be multiple height records. use the latest one
            for record in measurements.get('body').get('measuregrps'):
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
    def __init__(self, measuregrp):
        self._raw_data = measuregrp
        self.id = measuregrp.get('grpid')
        self.attrib = measuregrp.get('attrib')
        self.date = measuregrp.get('date')
        self.category = measuregrp.get('category')
        self.measures = [WithingsMeasure(m) for m in measuregrp['measures']]

    def __iter__(self):
        for measure in self.measures:
            yield measure

    def __len__(self):
        return len(self.measures)

    def get_datetime(self):
        return datetime.fromtimestamp(self.date)

    def get_raw_data(self):
        '''convenient function to get raw data'''
        return self.measures

    def get_weight(self):
        '''convenient function to get weight'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_WEIGHT:
                return measure.get_value()
        return None

    def get_height(self):
        '''convenient function to get height'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_HEIGHT:
                return measure.get_value()
        return None

    def get_fat_free_mass(self):
        '''convenient function to get fat free mass'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_FAT_FREE_MASS:
                return measure.get_value()
        return None

    def get_fat_ratio(self):
        '''convenient function to get fat ratio'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_FAT_RATIO:
                return measure.get_value()
        return None

    def get_fat_mass_weight(self):
        '''convenient function to get fat mass weight'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_FAT_MASS_WEIGHT:
                return measure.get_value()
        return None

    def get_diastolic_blood_pressure(self):
        '''convenient function to get diastolic blood pressure'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_DIASTOLIC_BLOOD_PRESSURE:
                return measure.get_value()
        return None

    def get_systolic_blood_pressure(self):
        '''convenient function to get systolic blood pressure'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_SYSTOLIC_BLOOD_PRESSURE:
                return measure.get_value()
        return None

    def get_heart_pulse(self):
        '''convenient function to get heart pulse'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_HEART_PULSE:
                return measure.get_value()
        return None

    def get_temperature(self):
        '''convenient function to get temperature'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_TEMPERATURE:
                return measure.get_value()
        return None

    def get_sp02(self):
        '''convenient function to get sp02'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_SP02:
                return measure.get_value()
        return None

    def get_body_temperature(self):
        '''convenient function to get body temperature'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_BODY_TEMPERATURE:
                return measure.get_value()
        return None

    def get_skin_temperature(self):
        '''convenient function to get skin temperature'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_SKIN_TEMPERATURE:
                return measure.get_value()
        return None

    def get_muscle_mass(self):
        '''convenient function to get muscle mass'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_MUSCLE_MASS:
                return measure.get_value()
        return None

    def get_hydration(self):
        '''convenient function to get hydration'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_HYDRATION:
                return measure.get_value()
        return None

    def get_bone_mass(self):
        '''convenient function to get bone mass'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_BONE_MASS:
                return measure.get_value()
        return None

    def get_pulse_wave_velocity(self):
        '''convenient function to get pulse wave velocity'''
        for measure in self.measures:
            if measure.type == WithingsMeasure.TYPE_PULSE_WAVE_VELOCITY:
                return measure.get_value()
        return None


class WithingsMeasure(object):
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

    def __init__(self, measure):
        self._raw_data = measure
        self.value = measure.get('value')
        self.type = measure.get('type')
        self.unit = measure.get('unit')

    def __str__(self):
        type_s = 'unknown'
        unit_s = ''
        if self.type == self.TYPE_WEIGHT:
            type_s = 'Weight'
            unit_s = 'kg'
        elif self.type == self.TYPE_HEIGHT:
            type_s = 'Height'
            unit_s = 'meter'
        elif self.type == self.TYPE_FAT_FREE_MASS:
            type_s = 'Fat Free Mass'
            unit_s = 'kg'
        elif self.type == self.TYPE_FAT_RATIO:
            type_s = 'Fat Ratio'
            unit_s = '%'
        elif self.type == self.TYPE_FAT_MASS_WEIGHT:
            type_s = 'Fat Mass Weight'
            unit_s = 'kg'
        elif self.type == self.TYPE_DIASTOLIC_BLOOD_PRESSURE:
            type_s = 'Diastolic Blood Pressure'
            unit_s = 'mmHg'
        elif self.type == self.TYPE_SYSTOLIC_BLOOD_PRESSURE:
            type_s = 'Systolic Blood Pressure'
            unit_s = 'mmHg'
        elif self.type == self.TYPE_HEART_PULSE:
            type_s = 'Heart Pulse'
            unit_s = 'bpm'
        elif self.type == self.TYPE_TEMPERATURE:
            type_s = 'Temperature'
            unit_s = 'celsius'
        elif self.type == self.TYPE_SP02:
            type_s = 'SP02'
            unit_s = '%'
        elif self.type == self.TYPE_BODY_TEMPERATURE:
            type_s = 'Body Temperature'
            unit_s = 'celsius'
        elif self.type == self.TYPE_SKIN_TEMPERATURE:
            type_s = 'Skin Temperature'
            unit_s = 'celsius'
        elif self.type == self.TYPE_MUSCLE_MASS:
            type_s = 'Muscle Mass'
            unit_s = 'kg'
        elif self.type == self.TYPE_HYDRATION:
            type_s = 'Hydration'
            unit_s = 'kg'
        elif self.type == self.TYPE_BONE_MASS:
            type_s = 'Bone Mass'
            unit_s = 'kg'
        elif self.type == self.TYPE_PULSE_WAVE_VELOCITY:
            type_s = 'Pulse Wave Velocity'
            unit_s = 'm/s'
        return '%s: %s %s' % (type_s, self.get_value(), unit_s)

    def get_value(self):
        return self.value * pow(10, self.unit)
