from __future__ import annotations

from pathlib import Path

import cloudscraper
import garth
import requests
from cloudscraper import CloudScraper

from withings_sync.get_logger import get_logger

logger = get_logger(__name__)


class LoginSucceeded(Exception):
    """Used to raise on LoginSucceeded"""


class LoginFailed(Exception):
    """Used to raise on LoginFailed"""


class APIException(Exception):
    """Used to raise on APIException"""


class GarminConnect:
    HOME: Path = Path.home()
    CONFIG_DIR: Path = HOME.joinpath(".config/withings-sync")
    UPLOAD_URL = "https://connect.garmin.com/upload-service/upload/.fit"

    def __init__(self):
        self.__class__.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.cookies_file = self.__class__.CONFIG_DIR.joinpath("garmin_cookies.json")
        self.headers_file = self.__class__.CONFIG_DIR.joinpath("garmin_headers.txt")

    @staticmethod
    def get_session(
        email: str | None = None, password: str | None = None
    ) -> CloudScraper:
        session: cloudscraper.CloudScraper = cloudscraper.CloudScraper()

        # self.print_cookies(session.cookies)
        try:
            garth.login(email, password)
        except Exception as ex:
            raise APIException(
                f"Authentication failure: {ex}. Did you enter correct credentials?"
            )

        session.headers.update(
            {
                "NK": "NT",
                "authorization": garth.client.oauth2_token.__str__(),
                "di-backend": "connectapi.garmin.com",
            }
        )

        return session

    def print_cookies(self, cookies):
        logger.debug("Cookies: ")
        for key, value in list(cookies.items()):
            logger.debug(" %s = %s", key, value)

    @staticmethod
    def login(username, password):
        """login to Garmin"""
        return GarminConnect.get_session(email=username, password=password)

    def upload_file(self, f, session):
        files = {"data": ("withings.fit", f)}

        res: requests.Response = session.post(
            self.UPLOAD_URL, files=files, headers={"nk": "NT"}
        )

        try:
            resp = res.json()
            if "detailedImportResult" not in resp:
                raise KeyError
        except (ValueError, KeyError):
            if res.status_code == 204:  # HTTP result 204 - 'no content'
                logger.error("No data to upload, try to use --from_date and --to_date")
            else:
                logger.error(
                    f"Bad response during GC upload: {res.status_code}. {res.content}"
                )

        return res.status_code in [200, 201, 204]
