import subprocess
import sys

def main():
    print("=== AVVIO TEST DI DOWNLOAD SU GITHUB RUNNER ===")
    res = subprocess.run("python test_youtube_download.py", shell=True)
    sys.exit(res.returncode)

if __name__ == "__main__":
    main()
