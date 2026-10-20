import unittest
from measure import analyze, instruction_count
from pathlib import Path
from tempfile import TemporaryDirectory


def samples(electron_times, node_times=()):
    return [dict(seconds=i / 10,
                 electron_cpu_ms=0.1 if i in electron_times else 0,
                 node_cpu_ms=0.1 if i in node_times else 0)
            for i in range(1, 641)]


class AnalysisTests(unittest.TestCase):
    def test_four_second_electron_with_small_node_noise(self):
        rows = samples(range(40, 641, 40), [151])
        result = analyze(rows)
        self.assertTrue(result['reproduced'])
        self.assertGreater(result['node']['cpu_ms'], 0)

    def test_one_second_activity_is_not_the_reported_bug(self):
        self.assertFalse(analyze(samples(range(10, 641, 10)))['reproduced'])

    def test_both_workloads_waking_every_four_seconds_is_not_a_reproduction(self):
        self.assertFalse(analyze(samples(range(40, 641, 40), range(40, 641, 40)))['reproduced'])

    def test_unsupported_instructions_are_not_reported_as_zero(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'perf.csv'
            path.write_text('0.1,<not supported>,,instructions:u,0,100,\n')
            self.assertIsNone(instruction_count(path))
            path.write_text('0.1,0,,instructions:u,100,100,\n')
            self.assertEqual(instruction_count(path), 0)


if __name__ == '__main__':
    unittest.main()
