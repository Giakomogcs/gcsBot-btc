import os
import pytest

os.environ['DATABASE_URL'] = 'sqlite:///test.db'
pytest.main(['-s', 'tests/test_data_manager.py'])
