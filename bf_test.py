from pybatfish.client.session import Session

bf = Session(host="localhost")
bf.set_network("suraksha_demo")

# Path points to the snapshot folder (the one that CONTAINS configs/)
bf.init_snapshot("batfish_snapshots/cisco_before", name="before", overwrite=True)

# 1. Did every file parse? (proves the config is valid for that vendor)
print("=== File Parse Status ===")
print(bf.q.fileParseStatus().answer().frame())

# 2. Any unrecognized or unsupported lines?
print("\n=== Parse Warnings ===")
print(bf.q.parseWarning().answer().frame())

# 3. Which device and vendor did Batfish detect?
print("\n=== Node Properties ===")
print(bf.q.nodeProperties().answer().frame())