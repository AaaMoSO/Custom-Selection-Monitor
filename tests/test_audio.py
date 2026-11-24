import math
import unittest

from app.audio import AudioDevice, AudioMeter, is_silent, list_output_devices, to_db


class AudioValueTests(unittest.TestCase):
    def test_to_db_reference_levels(self):
        self.assertAlmostEqual(to_db(1.0), 0.0)
        self.assertAlmostEqual(to_db(0.5), -6.02, places=2)
        self.assertAlmostEqual(to_db(0.1), -20.0)

    def test_to_db_floors_digital_silence(self):
        self.assertLessEqual(to_db(0.0), -170.0)
        self.assertLessEqual(to_db(1e-12), -170.0)

    def test_is_silent(self):
        self.assertTrue(is_silent(None))
        self.assertTrue(is_silent(-120.0))
        self.assertFalse(is_silent(-30.0))


class AudioMeterTests(unittest.TestCase):
    def test_level_is_rms_of_injected_blocks(self):
        meter = AudioMeter()
        meter._push_block(0.1)
        meter._push_block(0.1)
        level = meter.level_since_last()
        self.assertIsNotNone(level)
        self.assertAlmostEqual(level, to_db(0.1), places=2)

    def test_blocks_are_consumed(self):
        meter = AudioMeter()
        meter._push_block(0.2)
        self.assertIsNotNone(meter.level_since_last())
        self.assertIsNone(meter.level_since_last())

    def test_no_data_returns_none(self):
        meter = AudioMeter()
        self.assertIsNone(meter.level_since_last())
        meter.stop()

    def test_mixed_blocks_combine_by_rms(self):
        meter = AudioMeter()
        meter._push_block(0.0)
        meter._push_block(0.2)
        # sqrt((0^2 + 0.2^2)/2) = 0.1414
        self.assertAlmostEqual(meter.level_since_last(), to_db(0.2 / math.sqrt(2)), places=2)


class DeviceListingTests(unittest.TestCase):
    def test_list_output_devices_returns_audio_devices(self):
        devices = list_output_devices()
        self.assertIsInstance(devices, list)
        for device in devices:
            self.assertIsInstance(device, AudioDevice)
            self.assertTrue(device.id)
            self.assertTrue(device.name)


if __name__ == "__main__":
    unittest.main()
