#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime
from getpass import getpass

import argcomplete
import coloredlogs
import verboselogs

from withings_sync.fit import FitEncoderBloodPressure, FitEncoderWeight
from withings_sync.garmin import GarminConnect
from withings_sync.get_logger import get_logger
from withings_sync.trainerroad import TrainerRoad
from withings_sync.withings2 import WithingsAccount, WithingsConfig

coloredlogs.install(level=logging.INFO)
logger: verboselogs.VerboseLogger = get_logger(__name__)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "A tool for synchronisation of Withings " "(ex. Nokia Health Body) to Garmin Connect" " and Trainer Road."
        )
    )

    def date_parser(s: str) -> datetime:
        return datetime.strptime(s, "%Y-%m-%d")

    parser.add_argument(
        "--garmin-username",
        "-gu",
        default=os.environ.get("GARMIN_USERNAME"),
        type=str,
        metavar="GARMIN_USERNAME",
        help="username to login Garmin Connect.",
    )

    # parser.add_argument('--garmin-password', '--gp',
    #                     default=os.environ.get('GARMIN_PASSWORD'),
    #                     type=str,
    #                     metavar='GARMIN_PASSWORD',
    #                     help='password to login Garmin Connect.')

    parser.add_argument(
        "--trainerroad-username",
        "-tu",
        default=os.environ.get("TRAINERROAD_USERNAME"),
        type=str,
        metavar="TRAINERROAD_USERNAME",
        help="username to login TrainerRoad.",
    )

    # parser.add_argument('--trainerroad-password', '--tp',
    #                     default=os.environ.get('TRAINERROAD_PASSWORD'),
    #                     type=str,
    #                     metavar='TRAINERROAD_PASSWORD',
    #                     help='username to login TrainerRoad.')

    parser.add_argument(
        "--force-login", "-fl", action="store_true", help="Force login instead of using cached sessions."
    )

    parser.add_argument("--from_date", "-f", type=date_parser, default=None, metavar="DATE")

    parser.add_argument(
        "--to_date", "-t", type=date_parser, default=datetime.fromisoformat(date.today().isoformat()), metavar="DATE"
    )

    parser.add_argument("--to-fit", "-F", action="store_true", help="Write output file in FIT format.")

    parser.add_argument(
        "--to-json",
        "-J",
        action="store_true",
        help="Write output file in JSON format.",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        metavar="BASENAME",
        help="Write downloaded measurements to file.",
    )

    parser.add_argument(
        "--no-upload",
        action="store_true",
        help=("Won't upload to Garmin Connect and " "output binary-strings to stdout."),
    )

    parser.add_argument(
        "--features", nargs="+", default=[], metavar="BLOOD_PRESSURE", help="Enable Features like BLOOD_PRESSURE"
    )

    parser.add_argument(
        "--reset-config",
        action="store_true",
        help="Resets the config file allowing the user to authorize the app again.",
    )

    # Verbosity Options
    mutually_exclusive = parser.add_mutually_exclusive_group()
    mutually_exclusive.add_argument("--verbose", "-v", action="store_true", help="Run verbosely")
    mutually_exclusive.add_argument("--debug", "-d", action="store_true", help="Use DEBUG level logger.")

    # Enable automated argument completion
    argcomplete.autocomplete(parser)

    return parser.parse_args(args)


def sync_garmin(fit_file, args) -> bool:
    """Sync generated fit file to Garmin Connect."""
    garmin = GarminConnect()
    session = garmin.login(args.garmin_username, args.garmin_password)
    return garmin.upload_file(fit_file.getvalue(), session)


def sync_trainerroad(last_weight, args):
    """Sync measured weight to TrainerRoad"""
    t_road = TrainerRoad(args.trainerroad_username, args.trainerroad_password)
    t_road.connect()
    logger.info("Current TrainerRoad weight: %s kg ", t_road.weight)
    logger.info("Updating TrainerRoad weight to %s kg", last_weight)
    t_road.weight = round(last_weight, 1)
    t_road.disconnect()
    return t_road.weight


def generate_fitdata(sync_data) -> tuple[FitEncoderWeight | None, FitEncoderBloodPressure | None]:
    """Generate fit data from measured data"""
    logger.debug("Generating fit data...")

    weight_measurements = list(filter(lambda x: (x["type"] == "weight"), sync_data))
    blood_pressure_measurements = list(filter(lambda x: (x["type"] == "blood_pressure"), sync_data))

    fit_weight = None
    fit_blood_pressure = None

    if len(weight_measurements) > 0:
        fit_weight = FitEncoderWeight()
        fit_weight.write_file_info()
        fit_weight.write_file_creator()

        for record in weight_measurements:
            fit_weight.write_device_info(timestamp=record["date_time"])
            fit_weight.write_weight_scale(
                timestamp=record["date_time"],
                weight=record["weight"],
                percent_fat=record["fat_ratio"],
                percent_hydration=record["percent_hydration"],
                bone_mass=record["bone_mass"],
                muscle_mass=record["muscle_mass"],
                bmi=record["bmi"],
            )

        fit_weight.finish()
    else:
        logger.info("No weight data to sync for FIT file")

    if len(blood_pressure_measurements) > 0:
        fit_blood_pressure = FitEncoderBloodPressure()
        fit_blood_pressure.write_file_info()
        fit_blood_pressure.write_file_creator()

        for record in blood_pressure_measurements:
            fit_blood_pressure.write_device_info(timestamp=record["date_time"])
            fit_blood_pressure.write_blood_pressure(
                timestamp=record["date_time"],
                diastolic_blood_pressure=record["diastolic_blood_pressure"],
                systolic_blood_pressure=record["systolic_blood_pressure"],
                heart_rate=record["heart_pulse"],
            )

        fit_blood_pressure.finish()
    else:
        logger.info("No blood pressure data to sync for FIT file")

    logger.debug("Fit data generated...")
    return fit_weight, fit_blood_pressure


def generate_json_data(sync_data):
    """Generate fit data from measured data."""
    logger.debug("Generating json data...")

    json_data = {}
    for record in sync_data:
        sdt = str(record["date_time"])
        json_data[sdt] = {}
        for dataentry in record["raw_data"]:
            for k, jd in dataentry.json_dict().items():
                json_data[sdt][k] = jd
        if "bmi" in record:
            json_data[sdt]["BMI"] = {"Value": record["bmi"], "Unit": "kg/m^2"}
        if "percent_hydration" in record:
            json_data[sdt]["Percent_Hydration"] = {"Value": record["percent_hydration"], "Unit": "%"}
    logger.debug("Json data generated...")
    return json_data


def prepare_sync_data(height, groups, args):
    """Prepare measurement data to be sent"""
    sync_data = []

    last_date_time = None
    last_weight = None

    last_dt = None
    last_weight = None

    sync_dict = {}

    for group in groups:
        # Get extra physical measurements
        dt = group.get_datetime()

        # create a default group_data
        group_data = {
            "date_time": group.get_datetime(),
            "type": "None",
            "raw_data": group.get_raw_data(),
        }

        if dt not in sync_dict:
            sync_dict[dt] = {}

        if group.get_weight():
            weight = group.get_weight()
            hydration = group.get_hydration()

            if height and weight:
                bmi = round(weight / pow(height, 2), 1)
            else:
                bmi = None

            if hydration and weight:
                percent_hydration = round(hydration * 100.0 / weight, 2)
            else:
                percent_hydration = None

            group_data.update(
                {
                    # "date_time": group.get_datetime(),
                    "height": height,
                    "weight": group.get_weight(),
                    "fat_ratio": group.get_fat_ratio(),
                    "muscle_mass": group.get_muscle_mass(),
                    "hydration": group.get_hydration(),
                    "percent_hydration": percent_hydration,
                    "bone_mass": group.get_bone_mass(),
                    "pulse_wave_velocity": group.get_pulse_wave_velocity(),
                    "heart_pulse": group.get_heart_pulse(),
                    "bmi": bmi,
                    "raw_data": group.get_raw_data(),
                    "type": "weight",
                }
            )

            logger.debug(
                f"{dt} Detected data:\n"
                f"Record: {group_data['date_time']}, type={group_data['type']}\n"
                f"height={group_data['height']} m, "
                f"weight={group_data['weight']} kg, "
                f"fat_ratio={group_data['fat_ratio']} %, "
                f"muscle_mass={group_data['muscle_mass']} kg, "
                f"percent_hydration={group_data['percent_hydration']} %, "
                f"bone_mass={group_data['bone_mass']} kg, "
                f"bmi={group_data['bmi']}"
            )
        if group.get_diastolic_blood_pressure():
            group_data.update(
                {
                    # "date_time": group.get_datetime(),
                    "diastolic_blood_pressure": group.get_diastolic_blood_pressure(),
                    "systolic_blood_pressure": group.get_systolic_blood_pressure(),
                    "heart_pulse": group.get_heart_pulse(),
                    "raw_data": group.get_raw_data(),
                    "type": "blood_pressure",
                }
            )

            logger.debug(
                f"{dt} Detected data:\n"
                f"Record: {group_data['date_time']}, type={group_data['type']}\n"
                f"diastolic_blood_pressure={group_data['diastolic_blood_pressure']}, "
                f"systolic_blood_pressure={group_data['systolic_blood_pressure']}, "
                f"heart_pulse={group_data['heart_pulse']} bpm, "
            )

        if "weight" not in group_data and "diastolic_blood_pressure" not in group_data:
            logger.info(f"{dt} This Withings metric contains no weight data or blood pressure.  Not syncing...")
            group_data_log_raw_data(group_data)

            # for now, remove the entry as we're handling only weight and feature enabled data
            if dt in sync_dict:
                del sync_dict[dt]
            continue
        else:
            sync_dict[dt] = group_data

        # join groups with same timestamp
        # for k, v in group_data.items():
        #     sync_dict[dt][k] = v

    last_measurement_type = None

    for group_data in sync_dict.values():
        sync_data.append(group_data)
        debug_data = "\n".join([f"{k}={v}" for k, v in group_data.items()])
        logger.debug(f"Processed data:\n{debug_data}")
        if last_date_time is None or group_data["date_time"] > last_date_time:
            last_date_time = group_data["date_time"]
            last_measurement_type = group_data["type"]
            logger.debug(f"last_dt: {last_date_time} last_weight: {last_weight}")

    if last_measurement_type is None:
        logger.error("Invalid or no data detected")

    return last_measurement_type, last_date_time, sync_data


def group_data_log_raw_data(group_data):
    for data_entry in group_data["raw_data"]:
        logger.debug(f"{data_entry}")


def write_to_fit_file(filename, fit_data):
    logger.info(f"Writing fit file to {filename}.")
    try:
        with open(filename, "wb") as fit_file:
            fit_file.write(fit_data.getvalue())
    except OSError:
        logger.error(f"Unable to open output fit file! {filename}")


def write_to_file_when_needed(
    fit_data_weight: FitEncoderWeight | None,
    fit_data_blood_pressure: FitEncoderBloodPressure | None,
    json_data: dict,
    args: argparse.Namespace,
) -> None:
    """Write measurements to file when requested"""
    logger.info(fit_data_weight)
    if args.output is None:
        return
    if args.to_fit:
        if fit_data_weight is not None:
            write_to_fit_file(args.output + ".weight.fit", fit_data_weight)
        if fit_data_blood_pressure is not None:
            write_to_fit_file(args.output + ".blood_pressure.fit", fit_data_blood_pressure)

    if args.to_json:
        filename: str = args.output + ".json"
        logger.info(
            f"Writing JSON file to {filename}.",
        )
        try:
            with open(filename, "w", encoding="utf-8") as json_file:
                json.dump(json_data, json_file, indent=2)
        except OSError:
            logger.error(f"Unable to open output JSON file: '{filename}'")


def main(args: list[str] | None = None):
    args: argparse.Namespace = parse_args(args)

    # if args.garmin_password is None or args.garmin_password == "":
    #     args.garmin_password = getpass(prompt="Garmin Password: ")

    logging_level = logging.INFO
    if args.verbose:
        logging_level = verboselogs.VERBOSE
    elif args.debug:
        logging_level = logging.DEBUG

    coloredlogs.set_level(logging_level)

    config = WithingsConfig()

    if args.reset_config:
        config.reset()
        logger.info(
            "Succesfully reset the config. Next time you run withings-sync you will be prompted to "
            "re-authorize the app."
        )
        exit(0)

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
        logger.error("No measurements to upload for date or period specified")
        return -1

    last_measurement_type, last_date_time, syncdata = prepare_sync_data(height, groups, args)

    fit_data_weight, fit_data_blood_pressure = generate_fitdata(syncdata)
    json_data = generate_json_data(syncdata)

    write_to_file_when_needed(fit_data_weight, fit_data_blood_pressure, json_data, args)

    if not args.no_upload:
        # get weight entries (in case of only blood_pressure)
        only_weight_entries = list(filter(lambda x: (x["type"] == "weight"), syncdata))
        last_weight_exists = len(only_weight_entries) > 0
        # Upload to Trainer Road
        if args.trainerroad_username and last_weight_exists:
            # sort and get last weight
            last_weight_measurement = sorted(only_weight_entries, key=lambda x: x["date_time"])[-1]
            last_weight = last_weight_measurement["weight"]
            logger.info("Trainerroad username set -- attempting to sync")
            logger.info(f" Last weight {last_weight}")
            logger.info(f" Measured {last_date_time}")
            if sync_trainerroad(last_weight):
                logger.info("TrainerRoad update done!")
                config["last_update_garmin"] = end_date
        else:
            logger.info("No TrainerRoad username or a new measurement " "- skipping sync")

        # Upload to Garmin Connect
        if args.garmin_username and (fit_data_weight is not None or fit_data_blood_pressure is not None):
            logger.debug("attempting to upload fit file...")
            # if args.force_login:
            garmin_pw = getpass("Enter Garmin password: ")

            garmin = GarminConnect()
            session = garmin.login(args.garmin_username, garmin_pw)
            if fit_data_weight is not None and garmin.upload_file(fit_data_weight.getvalue(), session):
                logger.info("Fit file with weight information uploaded to Garmin Connect")
                config["last_update_garmin"] = end_date
            if fit_data_blood_pressure is not None and garmin.upload_file(fit_data_blood_pressure.getvalue(), session):
                logger.info("Fit file with blood pressure information uploaded to Garmin Connect")
                config["last_update_garmin"] = end_date
        else:
            logger.info("No Garmin username - skipping sync")
    else:
        logger.info("Skipping upload")

    # Save this sync so we don't re-download the same data again (if no range has been specified)

    config.save()

    return 0


if __name__ == "__main__":
    main()
