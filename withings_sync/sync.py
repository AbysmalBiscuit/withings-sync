#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta

import verboselogs
import coloredlogs

from withings_sync.fit import FitEncoder_Weight
from withings_sync.garmin import GarminConnect
from withings_sync.trainerroad import TrainerRoad
from withings_sync.withings2 import WithingsConfig, WithingsAccount, WithingsConfig
from withings_sync.get_logger import get_logger


logger = get_logger(__name__)


def parse_args(args: list[str] = None):
    parser = argparse.ArgumentParser(
            description=('A tool for synchronisation of Withings '
                         '(ex. Nokia Health Body) to Garmin Connect'
                         ' and Trainer Road.')
    )

    def date_parser(s):
        return datetime.strptime(s, '%Y-%m-%d')

    parser.add_argument('--garmin-username', '--gu',
                        default=os.environ.get('GARMIN_USERNAME'),
                        type=str,
                        metavar='GARMIN_USERNAME',
                        help='username to login Garmin Connect.')
    parser.add_argument('--garmin-password', '--gp',
                        default=os.environ.get('GARMIN_PASSWORD'),
                        type=str,
                        metavar='GARMIN_PASSWORD',
                        help='password to login Garmin Connect.')

    parser.add_argument('--trainerroad-username', '--tu',
                        default=os.environ.get('TRAINERROAD_USERNAME'),
                        type=str,
                        metavar='TRAINERROAD_USERNAME',
                        help='username to login TrainerRoad.')
    parser.add_argument('--trainerroad-password', '--tp',
                        default=os.environ.get('TRAINERROAD_PASSWORD'),
                        type=str,
                        metavar='TRAINERROAD_PASSWORD',
                        help='username to login TrainerRoad.')

    parser.add_argument("--force-login", "-fl", action="store_true",
                        help="Force login instead of using cached sessions.")

    parser.add_argument('--from_date', '-f',
                        type=date_parser,
                        default=None,
                        metavar='DATE')

    parser.add_argument('--to_date', '-t',
                        type=date_parser,
                        default=datetime.fromisoformat(date.today().isoformat()),
                        metavar='DATE')

    parser.add_argument('--no-upload',
                        action='store_true',
                        help=('Won\'t upload to Garmin Connect and '
                              'output binary-strings to stdout.'))
    mutually_exclusive = parser.add_mutually_exclusive_group()
    mutually_exclusive.add_argument('--verbose', '-v',
                                    action='store_true',
                                    help='Run verbosely')
    mutually_exclusive.add_argument("--debug", "-d",
                                    action="store_true",
                                    help="Use DEBUG level logger.")

    return parser.parse_args(args)


def main():
    args = parse_args()

    # if args.garmin_password is None or args.garmin_password == "":
    #     args.garmin_password = getpass(prompt="Garmin Password: ")

    logging_level = logging.INFO
    if args.verbose:
        logging_level = verboselogs.VERBOSE
    elif args.debug:
        logging_level = logging.DEBUG

    coloredlogs.set_level(logging_level)

    config = WithingsConfig()

    # Withings API
    withings = WithingsAccount(config)

    # Configure date range for update
    if args.from_date is None:
        if config["last_update_garmin"] is not None:
            start_date = config["last_update_garmin"] + 1
        else:
            start_date = int(datetime.fromisoformat(date.today().isoformat()).timestamp())
    else:
        start_date = int(args.from_date.timestamp())

    end_date = int(args.to_date.timestamp()) + 86399

    logger.verbose(f"Updating from: {date.fromtimestamp(start_date)} to {date.fromtimestamp(end_date)}")

    height = withings.get_height()

    groups = withings.get_measurements(start_date=start_date, end_date=end_date)

    # Only upload if there are measurement returned
    if groups is None or len(groups) == 0:
        logger.error('No measurements to upload for date or period specified')
        return -1

    # Create FIT file
    logger.debug('Generating fit file...')
    fit = FitEncoder_Weight()
    fit.write_file_info()
    fit.write_file_creator()

    last_dt = None
    last_weight = None

    for group in groups:
        # Get extra physical measurements
        dt = group.get_datetime()
        weight = group.get_weight()
        percent_fat = group.get_fat_ratio()
        muscle_mass = group.get_muscle_mass()
        hydration = group.get_hydration()
        bone_mass = group.get_bone_mass()
        raw_data = group.get_raw_data()

        if weight is None:
            logger.info('This Withings metric contains no weight data.  Not syncing...')
            logger.debug('Detected data: ')
            for data_entry in raw_data:
                logger.debug(data_entry)
            continue

        if height and weight:
            bmi = round(weight / pow(height, 2), 1)
        else:
            bmi = None

        if hydration and weight:
            percent_hydration = hydration * 100.0 / weight
        else:
            percent_hydration = None

        fit.write_device_info(timestamp=dt)
        fit.write_weight_scale(timestamp=dt,
                               weight=weight,
                               percent_fat=percent_fat,
                               percent_hydration=percent_hydration,
                               bone_mass=bone_mass,
                               muscle_mass=muscle_mass,
                               bmi=bmi)
        logger.debug(f"Record: {dt} weight={weight}kg, percent_fat={percent_fat}%, muscle_mass={muscle_mass}kg, hydration="
                     f"{hydration}%, boned_mass={bone_mass}kg, bmi={bmi}")

        if last_dt is None or dt > last_dt:
            last_dt = dt
            last_weight = weight

    fit.finish()

    if last_weight is None:
        logger.error('Invalid weight')
        return -1

    if args.no_upload:
        sys.stdout.buffer.write(fit.getvalue())
        return 0

    # Upload to Trainer Road
    if args.trainerroad_username:
        logger.info('Trainerroad username set -- attempting to sync')
        logger.info(' Last weight {}'.format(last_weight))
        logger.info(' Measured {}'.format(last_dt))

        tr = TrainerRoad(args.trainerroad_username, args.trainerroad_password)
        tr.connect()

        logger.info(f'Current TrainerRoad weight: {tr.weight} kg ')
        logger.info(f'Updating TrainerRoad weight to {last_weight} kg')

        tr.weight = round(last_weight, 1)
        tr.disconnect()

        logger.info('TrainerRoad update done!')
    else:
        logger.info('No Trainerroad username or a new measurement '
                     '- skipping sync')

    # Upload to Garmin Connect
    if args.garmin_username:
        garmin = GarminConnect()
        session = garmin.login(args.garmin_username, args.garmin_password, args.force_login)
        logger.debug('attempting to upload fit file...')
        r = garmin.upload_file(fit.getvalue(), session)
        if r:
            logger.info('Fit file uploaded to Garmin Connect')
        config["last_update_garmin"] = end_date
    else:
        logger.info('No Garmin username - skipping sync')

    config.save()


if __name__ == "__main__":
    main()
