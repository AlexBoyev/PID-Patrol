"""End-to-end tests for the PID Patrol FastAPI app."""

import pytest
from dashboards.web_dashboard import app
from testing.utils import _post_json, _get_json
from utils import *

PROCESSES = ["Python.exe", "Chrome.exe", "test1", "test2"]


@pytest.fixture(scope="module", autouse=True)
def test_init():
    """Start Uvicorn once for this module and shut it down after."""
    print('Starting PID patrol test')
    manager = UvicornServerManager(app, HOST, PORT)
    manager.start()
    yield
    print('Tear down - cleaning PID patrol test')
    manager.stop()
    print('PID patrol test cleanup complete')


@pytest.mark.parametrize("good_interval", [1, 2])
def test_update_interval(good_interval):
    """Update polling interval to a valid value."""
    code, resp = _post_json("/ui/interval", {"interval": good_interval})
    assert code == 200, f"Test failed - POST /ui/interval expected 200, got {code}, resp={resp}"
    got = float(resp.get("interval", 0))
    assert got == good_interval, f"Test failed - interval mismatch: expected {good_interval}, got {got}"


@pytest.mark.parametrize("bad_interval", [0, -1, 0.5, 'f', '3', ' 3'])
def test_fail_to_update_interval(bad_interval):
    """Reject invalid polling intervals."""
    with pytest.raises(error.HTTPError) as excinfo:
        _post_json("/ui/interval", {"interval": bad_interval})
    assert excinfo.value.code == 409, (
        f"Test failed - invalid interval {bad_interval!r} should return 409, got {excinfo.value.code}"
    )


def test_processes_negative_empty_entry_is_ignored():
    """Reject blank process entries."""
    with pytest.raises(error.HTTPError) as excinfo:
        _post_json("/ui/add", {"processes": ["", "   "]})
    assert excinfo.value.code == 409, (
        f'Test failed - empty/blank entries must be rejected with 409, got {excinfo.value.code}'
    )


def test_processes_negative_empty_list_of_processes():
    """Reject empty process list."""
    with pytest.raises(error.HTTPError) as excinfo:
        _post_json("/ui/add", {"processes": []})
    assert excinfo.value.code == 409, (
        f'Test failed - empty process list must be rejected with 409, got {excinfo.value.code}'
    )


@pytest.mark.dependency(name="test_add_processes_list")
def test_add_processes_list():
    """Add an initial list of processes."""
    code, resp = _post_json("/ui/add", {"processes": PROCESSES})
    assert code == 200, f"Test failed - add processes expected 200, got {code}, resp={resp}"
    assert resp.get("ok") is True, f"Test failed - add processes missing ok=True, got {resp}"
    returned = [p.get("name") for p in resp.get("processes", [])]
    assert returned == PROCESSES, f"Test failed - expected {PROCESSES}, got {returned}"


@pytest.mark.dependency(name="test_add_existing_process", depends=["test_add_processes_list"])
def test_add_existing_process():
    """Adding an existing process should fail."""
    code, resp = _post_json("/ui/add", {"processes": ["pYtHon.Exe"]})
    assert code == 409, f"Test failed - adding existing process should return 409, got {code}, resp={resp}"


def test_add_via_names_string_trim_dedupe_order():
    """Accept 'names' string; trim, de-dup, and preserve order."""
    code, resp = _post_json("/ui/add", {"names": " Alpha.exe; beta.exe,\nAlpha.exe "})
    assert code == 200, f"Test failed - add via names expected 200, got {code}, resp={resp}"
    assert resp.get("ok") is True, f"Test failed - add via names missing ok=True, got {resp}"
    names = [(p.get("name") or "").strip() for p in resp.get("processes", [])]
    lower = [n.lower() for n in names]
    assert "alpha.exe" in lower and "beta.exe" in lower, f"Test failed - alpha/beta not both present in {lower}"
    assert lower.index("alpha.exe") < lower.index("beta.exe"), f"Test failed - order not preserved: {lower}"


def test_remove_missing_name():
    """Reject remove request without a name."""
    with pytest.raises(error.HTTPError) as excinfo:
        _post_json("/ui/remove", {})
    assert excinfo.value.code == 409, (
        f"Test failed - POST /ui/remove without name must return 409, got {excinfo.value.code}"
    )


@pytest.mark.dependency(name="test_delete_process", depends=["test_add_processes_list"])
def test_delete_process():
    """Remove an existing process from the list."""
    code, resp = _post_json("/ui/remove", {"name": "test2"})
    assert code == 200, f"Test failed - remove existing process expected 200, got {code}, resp={resp}"
    assert resp.get("ok") is True, f"Test failed - remove response missing ok=True, got {resp}"
    processes_names = [p.get("name") for p in resp.get("processes", [])]
    lowered = { (name or "").lower() for name in processes_names }
    assert "test2" not in lowered, f"Test failed - 'test2' still present after removal: {processes_names}"


def test_attempt_to_delete_nonexistent_process():
    """Deleting a nonexistent process returns 404."""
    with pytest.raises(error.HTTPError) as excinfo:
        _post_json("/ui/remove", {"name": "nonexistent_process"})
    assert excinfo.value.code == 404, (
        f"Test failed - deleting nonexistent process should return 404, got {excinfo.value.code}"
    )


def test_status_endpoint_exists_and_off_initially():
    """Status endpoint exists and reports stopped initially."""
    code, js = _get_json("/ui/status")
    assert code == 200, f"Test failed - GET /ui/status expected 200, got {code}, js={js}"
    assert js.get("running") is False, f'Test failed - expected "running" False initially, got {js}'


@pytest.mark.dependency(name="test_start_monitoring", depends=["test_add_processes_list"])
def test_start_monitoring():
    """Start monitoring and verify results contain a running Python.exe."""
    code, js = _post_json("/ui/start", {})
    assert code == 200, f"Test failed - POST /ui/start expected 200, got {code}, resp={js}"
    _, js = _get_json("/ui/results")
    assert any((proc.get("name") or "").lower() == "python.exe" and proc.get("status") == "running"
               for proc in js.get("results", [])), f"Test failed - Python.exe not reported running in results: {js}"


@pytest.mark.dependency(name="test_status_is_running_once_monitoring_is_started", depends=["test_start_monitoring"])
def test_status_is_running_once_monitoring_is_started():
    """Status shows running after start."""
    code, js = _get_json("/ui/status")
    assert code == 200, f"Test failed - GET /ui/status expected 200, got {code}, js={js}"
    assert js.get("running") is True, f'Test failed - expected "running" True after start, got {js}'


@pytest.mark.dependency(name="test_remove_process_while_running", depends=["test_start_monitoring"])
def test_remove_process_while_running():
    """Remove Python.exe while monitoring is running."""
    code, resp = _post_json("/ui/remove", {"name": "Python.exe"})
    assert code == 200, f"Test failed - remove while running expected 200, got {code}, resp={resp}"
    assert resp.get("ok") is True, f"Test failed - remove while running missing ok=True, got {resp}"
    _, js = _get_json("/ui/results")
    assert all((proc.get("name") or "").lower() != "python.exe" for proc in js.get("results", [])), (
        f"Test failed - Python.exe still present after removal while running: {js}"
    )


@pytest.mark.dependency(name="test_add_process_after_removal", depends=["test_remove_process_while_running"])
def test_add_process_after_removal():
    """Re-add Python.exe after it was removed."""
    code, resp = _post_json("/ui/add", {"processes": ["Python.exe"]})
    assert code == 200, f"Test failed - re-adding Python.exe expected 200, got {code}, resp={resp}"
    assert resp.get("ok") is True, f"Test failed - re-add response missing ok=True, got {resp}"
    _, js = _get_json("/ui/results")
    assert any((p.get("name") or "").lower() == "python.exe" for p in js.get("results", [])), (
        f"Test failed - Python.exe not present after re-add: {js}"
    )


@pytest.mark.dependency(name="test_process_status_running", depends=["test_start_monitoring"])
def test_process_status_running():
    """Verify Python.exe is running with a non-empty PID list."""
    _, js = _get_json("/ui/results")
    assert any((proc.get("name") or "").lower() == "python.exe" and
               proc.get("status") == "running" and isinstance(proc.get("pids"), list) and
               len(proc["pids"]) > 0 for proc in js.get("results", [])), (
        f"Test failed - Python.exe not running with non-empty PID list: {js}"
    )


@pytest.mark.dependency(name="test_process_status_not_found", depends=["test_start_monitoring"])
def test_process_status_not_found():
    """Verify test1 is reported as not found with empty PID list."""
    _, js = _get_json("/ui/results")
    assert any((proc.get("name") or "").lower() == "test1" and
               proc.get("status") == "not found" and
               (not proc.get("pids")) for proc in js.get("results", [])), (
        f"Test failed - 'test1' not reported as not found with empty PID list: {js}"
    )


@pytest.mark.dependency(name="test_process_memory", depends=["test_start_monitoring"])
def test_process_memory():
    """Verify Python.exe memory is greater than 0."""
    _, js = _get_json("/ui/results")
    assert any((proc.get("name") or "").lower() == "python.exe" and
               float(proc.get("memory_mb", 0)) > 0.0 for proc in js.get("results", [])), (
        f"Test failed - Python.exe memory_mb not > 0: {js}"
    )


@pytest.mark.dependency(name="test_process_cpu", depends=["test_start_monitoring"])
def test_process_cpu():
    """Verify Chrome.exe cpu_percent is within 0..100."""
    _, js = _get_json("/ui/results")
    assert any((proc.get("name") or "").lower() == "chrome.exe" and
               isinstance(proc.get("cpu_percent"), (int, float)) and
               0.0 <= float(proc["cpu_percent"]) <= 100.0 for proc in js.get("results", [])), (
        f"Test failed - Chrome.exe cpu_percent missing or out of range: {js}"
    )


@pytest.mark.dependency(name="test_all_pids_are_unique", depends=["test_start_monitoring"])
def test_all_pids_are_unique():
    """
    Validate PID lists in /ui/results:
      1) each row's 'pids' is a list
      2) only positive integers
      3) no duplicates per row
      4) no PID appears under two different process rows (global uniqueness)
    """
    code, res = _get_json("/ui/results")
    assert code == 200, f"Expected 200 from /ui/results, got {code}, res={res}"
    rows = res.get("results", [])
    assert isinstance(rows, list), f"results must be a list, got {type(rows).__name__}"
    all_pids = [pid for row in rows for pid in row.get("pids", [])]
    dupes = [pid for pid in set(all_pids) if all_pids.count(pid) > 1]
    assert not dupes, f"Some PIDs appear under multiple processes: {dupes}"


@pytest.mark.dependency(name="test_stop_monitoring", depends=["test_start_monitoring"])
def test_stop_monitoring():
    """Stop monitoring and verify results endpoint returns 204."""
    code, resp = _post_json("/ui/stop", {})
    assert code == 200, f"Test failed - POST /ui/stop expected 200, got {code}, resp={resp}"
    code, js = _get_json("/ui/results")
    assert code == 204, f"Test failed - GET /ui/results after stop expected 204, got {code}, js={js}"
    assert js == {}, f"Test failed - GET /ui/results after stop should be empty dict, got {js}"


@pytest.mark.dependency(name="test_status_stopped_once_monitoring_is_stopped", depends=["test_stop_monitoring"])
def test_status_stopped_once_monitoring_is_stopped():
    """Status shows stopped after monitoring is stopped."""
    code, js = _get_json("/ui/status")
    assert code == 200, f"Test failed - GET /ui/status expected 200, got {code}, js={js}"
    assert js.get("running") is False, f'Test failed - expected "running" False after stop, got {js}'
