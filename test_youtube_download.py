import subprocess
import os

def test_download(video_url):
    print(f"=== TEST DOWNLOAD YOUTUBE: {video_url} ===")
    video_filename = "test_video.mp4"
    if os.path.exists(video_filename):
        os.remove(video_filename)
        
    # Usiamo yt-dlp con extractor-args ios/android per bypassare il blocco bot
    cmd = f'yt-dlp -f "best[ext=mp4]/mp4" --extractor-args "youtube:player-client=ios,android" -o "{video_filename}" "{video_url}"'
    print(f"Esecuzione: {cmd}")
    
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print("Return Code:", res.returncode)
    print("STDOUT:", res.stdout[:1000])
    print("STDERR:", res.stderr[:1000])
    
    if os.path.exists(video_filename) and os.path.getsize(video_filename) > 0:
        print("🎉 DOWNLOAD COMPLETED SUCCESSFUL!")
        os.remove(video_filename)
        return True
    else:
        print("❌ DOWNLOAD FAILED!")
        return False

if __name__ == "__main__":
    test_download("https://www.youtube.com/watch?v=KxfRa-N40HU")
