"""Task 12 fix round 3 (C-1 evidence tool, not product code): a pytest plugin that repeats every selected test
--s1-repeat N times (each repetition a separate test id with its own tmp_path). Usage, from research/s1:
  python -m pytest -p t12_fix3_repeat_plugin --s1-repeat 200 "s1_tests/<file>::<test>" (with s1_evidence on PYTHONPATH)."""


def pytest_addoption(parser):
    parser.addoption("--s1-repeat", type=int, default=1, help="repeat each selected test N times")


def pytest_generate_tests(metafunc):
    n = metafunc.config.getoption("s1_repeat")
    if n > 1:
        metafunc.fixturenames.append("s1_rep")
        metafunc.parametrize("s1_rep", range(n), ids=lambda i: f"rep{i:03d}")
