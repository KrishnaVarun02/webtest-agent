# Sample application

This dependency-free local website provides a safe target for capture and generated tests.

```bash
python3 app.py --port 8765
python3 -m unittest -v test_app.py
```

The seeded demonstration credentials are `sample_user` / `sample_password`. They are
test data only. Generated tests read them from environment variables.
