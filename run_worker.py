import sys
sys.stdout = open(r"F:\FamilyArchive\worker_output.txt", "w")
sys.stderr = sys.stdout

exec(open(r"F:\FamilyArchive\worker.py").read())

sys.stdout.close()
