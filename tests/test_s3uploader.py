import unittest
from unittest.mock import patch, MagicMock
from s3_upload import s3uploader

class TestConfig(unittest.TestCase):
    def test_parse_args_defaults(self):
        args = []
        config = s3uploader.Config(args)
        d = config.to_dict()
        self.assertIn('user', d)
        self.assertIn('password', d)
        self.assertIn('output', d)
        self.assertEqual(d['output'], '/output')

    def test_parse_args_custom(self):
        args = ['--user', 'alice', '-p', 'secret', '-o', '/tmp']
        config = s3uploader.Config(args)
        d = config.to_dict()
        self.assertEqual(d['user'], 'alice')
        self.assertEqual(d['password'], 'secret')
        self.assertEqual(d['output'], '/tmp')

class TestS3Uploader(unittest.TestCase):
    @patch('s3_upload.s3uploader.boto3.client')
    @patch('s3_upload.s3uploader.os.walk')
    @patch('s3_upload.s3uploader.os.remove')
    def test_upload_and_remove(self, mock_remove, mock_walk, mock_boto):
        # Setup mocks
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_walk.return_value = [
            ('/tmp/videos', [], ['file1.mp4', 'file2.h264'])
        ]
        # Patch config
        with patch('s3_upload.s3uploader.cfg', s3uploader.Config(['--user', 'bob', '-o', '/tmp'])):
            with patch('s3_upload.s3uploader.S3_BUCKET_NAME', 'test-bucket'):
                with patch('s3_upload.s3uploader.S3_PREFIX', 'test-prefix'):
                    with patch('s3_upload.s3uploader.local_directory', '/tmp/videos'):
                        # Re-import to run the upload loop
                        import importlib
                        importlib.reload(s3uploader)
                        # Check upload_file called for each file
                        self.assertEqual(mock_s3.upload_file.call_count, 2)
                        mock_remove.assert_any_call('/tmp/videos/file1.mp4')
                        mock_remove.assert_any_call('/tmp/videos/file2.h264')

if __name__ == '__main__':
    unittest.main()
