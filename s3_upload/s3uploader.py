import os, sys
import boto3
from argparse import ArgumentParser
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Config:
    def __init__(self, args):
        """
        Parse the arguments
        params:
            args: the arguments
        """
        self.parser = self.__init_parser__()
        self.arg_dict = self.parse_args(args)

    def parse_args(self, args):
        return vars(self.parser.parse_args())

    def __init_parser__(self):
        parser = ArgumentParser()
        parser.add_argument(
            "-u",
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

    def to_dict(self):
        return self.arg_dict


cfg = Config(sys.argv[1:])
config = cfg.to_dict()
S3_BUCKET_NAME = "gt-training-data"
local_directory = "{}/videos".format(config["output"])
S3_PREFIX = "audit-cams/{}".format(config["user"])
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("GT_AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("GT_AWS_SECRET_ACCESS_KEY"),
)

logger = Logger("s3_uploader").logger
logger.info("Configuration: {}".format(cfg.to_dict()))

# Iterate through the local files
for root, dirs, files in os.walk(local_directory):
    for file in files:
        local_path = os.path.join(root, file)
        relative_path = os.path.relpath(local_path, local_directory)
        s3_key = os.path.join(S3_PREFIX, relative_path)

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
