def pytest_runtest_setup(item):
    """Function to print Starting test before each test"""
    print(f'\nStarting test - "{item.name}" ...')


def pytest_runtest_makereport(item, call):
    """Function to call that the test passed in case its passed."""
    if call.when == "call" and call.excinfo is None:
        print(f'\nTest passed - "{item.name}" as expected..')