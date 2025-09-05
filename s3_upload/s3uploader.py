import os
import sys
import boto3
from argparse import ArgumentParser
import logging
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Config:
    def __init__(self, args: List[str]) -> None:
        """
        Parse the arguments
        params:
            args: the arguments
        """
        self.parser: ArgumentParser = self.__init_parser__()
        self.arg_dict: Dict[str, Any] = self.parse_args(args)

    def parse_args(self, args: List[str]) -> Dict[str, Any]:
        return vars(self.parser.parse_args(args))

    def __init_parser__(self) -> ArgumentParser:
        parser = ArgumentParser()
        parser.add_argument(
            "--user",
            help="Username",
            default=os.environ.get("DEVICE_SERIAL", "abcdefgh"),
        )
        parser.add_argument(
            "-p",
            "--password",

            help="Password",
            default=os.environ.get("DEVICE_PASSWORD", "abcdefgh"),
        )
        parser.add_argument("-o", "--output", help="output", default="/output")
        return parser

    def to_dict(self) -> Dict[str, Any]:
        return self.arg_dict


cfg: Config = Config(sys.argv[1:])
config: Dict[str, Any] = cfg.to_dict()
S3_BUCKET_NAME: str = "gt-training-data"
local_directory: str = "{}/videos".format(config["output"])
S3_PREFIX: str = "audit-cams/{}".format(config["user"])
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("GT_AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("GT_AWS_SECRET_ACCESS_KEY"),
)
config: Dict[str, Any] = cfg.to_dict()
S3_BUCKET_NAME: str = "gt-training-data"
local_directory: str = "{}/videos".format(config["output"])
S3_PREFIX: str = "audit-cams/{}".format(config["user"])
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("GT_AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("GT_AWS_SECRET_ACCESS_KEY"),
)


logger.info("Configuration: {}".format(cfg.to_dict()))

# Iterate through the local files
for root, dirs, files in os.walk(local_directory):
    root: str
    dirs: List[str]
    files: List[str]
    for file in files:
        file: str
        local_path: str = os.path.join(root, file)
        relative_path: str = os.path.relpath(local_path, local_directory)
        s3_key: str = os.path.join(S3_PREFIX, relative_path)

        # Check if the file has a .h264 extension
        # Upload the file to S3 without conversion
        logger.info(
            f"Uploading {local_path} to S3 bucket {S3_BUCKET_NAME} with key {s3_key}"
        )
        s3.upload_file(local_path, S3_BUCKET_NAME, s3_key)
        logger.info(
            f"Uploaded {local_path} to S3 bucket {S3_BUCKET_NAME} with key {s3_key}"
        )

        # Delete the local file after upload
        os.remove(local_path)
        logger.info(f"Deleted {local_path} after upload")
