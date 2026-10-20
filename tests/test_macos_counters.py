import runpy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


class MacCountersTests(unittest.TestCase):
    def test_apple_silicon_mach_ticks_are_converted_to_nanoseconds(self):
        lib = Mock()

        def timebase(pointer):
            pointer._obj.numer = 125
            pointer._obj.denom = 3
            return 0

        def usage(pid, flavor, pointer):
            pointer._obj.user_time = 24000
            pointer._obj.system_time = 48000
            pointer._obj.instructions = 123456
            return 0

        lib.mach_timebase_info.side_effect = timebase
        lib.proc_pid_rusage.side_effect = usage
        with patch('ctypes.CDLL', return_value=lib):
            module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'macos_counters.py'))
            result = module['snapshot'](123)
        self.assertEqual(result['cpu_ns'], 3000000)
        self.assertEqual(result['instructions'], 123456)
