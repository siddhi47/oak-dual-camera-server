import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.rpi_dual_cam_server import cam_server

class TestDevicePipelines(unittest.TestCase):
    def setUp(self):
        self.mxid = "testmxid"
        self.label = "testlabel"
        self.device = cam_server.DevicePipelines(self.mxid, self.label)

    def test_initial_state(self):
        self.assertEqual(self.device.mxid, self.mxid)
        self.assertEqual(self.device.label, self.label)
        self.assertFalse(self.device.is_recording())
        self.assertIsNone(self.device.latest_jpeg())

    @patch("src.rpi_dual_cam_server.cam_server.Path.mkdir")
    def test_start_recording_creates_chunk(self, mock_mkdir):
        out_dir = Path("/tmp/testoutput")
        with patch.object(self.device, "_open_new_chunk_locked") as mock_open_chunk:
            self.device.start_recording(out_dir)
            mock_open_chunk.assert_called_once_with(out_dir)
            self.assertTrue(self.device.is_recording())

    def test_stop_recording_resets_state(self):
        self.device._recording = True
        self.device._h264_file = MagicMock()
        self.device._current_chunk_path = Path("/tmp/test.h264")
        with patch.object(self.device, "_enqueue_remux") as mock_remux:
            self.device.stop_recording()
            self.assertFalse(self.device.is_recording())
            mock_remux.assert_called()

class TestCameraManager(unittest.TestCase):
    def setUp(self):
        self.mapping = {"narrow": "mxid1", "wide": "mxid2"}
        with patch("src.rpi_dual_cam_server.cam_server.DevicePipelines") as MockDevice:
            self.manager = cam_server.CameraManager(self.mapping)
            self.mock_devices = MockDevice

    def test_toggle_switches_label(self):
        first = self.manager.current_label
        second = self.manager.toggle()
        self.assertNotEqual(first, second)
        self.assertIn(second, self.mapping.keys())

    def test_set_current(self):
        self.manager.set_current("wide")
        self.assertEqual(self.manager.current_label, "wide")

if __name__ == "__main__":
    unittest.main()
