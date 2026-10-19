import os
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SEED_ACCOUNTS"] = "acc_demo:100000.00,acc_bob:500.00,canary-remediation:1000000000.00"
