#!/usr/bin/env python3
"""AUTOFOX EDIT MVP: scene detection + motion-based clip selection + FFmpeg render."""
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

def run(cmd, capture=False):
    try:
        return subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    except FileNotFoundError:
        raise RuntimeError("FFmpeg غير موجود. ثبّته: pkg install ffmpeg")
    except subprocess.CalledProcessError as e:
        raise RuntimeError((e.stderr or "FFmpeg failed")[-1800:])

def duration_of(path):
    p=run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],True)
    return float(p.stdout.strip())

def detect_scenes(path, threshold):
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector
    video=open_video(str(path)); manager=SceneManager(); manager.add_detector(ContentDetector(threshold=threshold,min_scene_len=12))
    manager.detect_scenes(video,show_progress=True)
    scenes=[]
    for start,end in manager.get_scene_list():
        a,b=start.get_seconds(),end.get_seconds()
        if b-a>=0.8: scenes.append((max(0,a),max(a+0.1,b)))
    return scenes or [(0,duration_of(path))]

def motion_score(path,a,b):
    import numpy as np
    p=subprocess.run(["ffmpeg","-v","error","-ss",f"{a:.3f}","-i",str(path),"-t",f"{max(.2,b-a):.3f}","-vf","fps=2,scale=96:54,format=gray","-f","rawvideo","-"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    size=96*54; count=len(p.stdout)//size
    if count<2: return min(b-a,10)*0.1
    frames=np.frombuffer(p.stdout[:count*size],dtype=np.uint8).reshape(count,54,96)
    return float(np.mean([np.mean(np.abs(frames[i].astype(np.int16)-frames[i-1].astype(np.int16))) for i in range(1,count)]))

def main():
    ap=argparse.ArgumentParser(description="AUTOFOX EDIT — مونتاج تلقائي أولي")
    ap.add_argument("video"); ap.add_argument("--output"); ap.add_argument("--seconds",type=float,default=30)
    ap.add_argument("--max-clip",type=float,default=5); ap.add_argument("--threshold",type=float,default=27)
    ap.add_argument("--width",type=int,default=1920); ap.add_argument("--crf",type=int,default=23)
    args=ap.parse_args(); src=Path(args.video).expanduser()
    if not src.is_file(): print("لم أجد ملف الفيديو:",src); return 2
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"): print("ثبّت FFmpeg: pkg install ffmpeg"); return 2
    out=Path(args.output).expanduser() if args.output else src.with_name(src.stem+"_AUTOFOX.mp4")
    if src.resolve()==out.resolve(): print("مسار الإخراج يجب أن يختلف عن الأصل."); return 2
    try:
        total=duration_of(src); print(f"مدة الفيديو: {total:.1f} ثانية")
        print("1/3 تحليل المشاهد..."); scenes=detect_scenes(src,args.threshold); print(f"مشاهد مكتشفة: {len(scenes)}")
        print("2/3 تقييم الحركة واختيار اللقطات...")
        scored=[]
        for i,(a,b) in enumerate(scenes):
            scored.append({"index":i,"start":a,"end":b,"duration":b-a,"motion":motion_score(src,a,b)})
        chosen=[]; used=0
        for item in sorted(scored,key=lambda x:x["motion"],reverse=True):
            length=min(item["duration"],args.max_clip)
            if used+length>max(5,args.seconds) and chosen: continue
            chosen.append(item); used+=length
            if used>=max(5,args.seconds): break
        chosen.sort(key=lambda x:x["start"])
        print(f"لقطات مختارة: {len(chosen)}")
        out.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="autofox_") as td:
            td=Path(td); clips=[]
            for n,item in enumerate(chosen,1):
                length=min(item["duration"],args.max_clip); start=item["start"]+max(0,(item["duration"]-length)/2)
                clip=td/f"clip_{n:03}.mp4"
                vf=f"scale='min({args.width},iw)':-2:force_original_aspect_ratio=decrease,setsar=1,fps=30,format=yuv420p"
                run(["ffmpeg","-y","-v","error","-ss",f"{start:.3f}","-i",str(src),"-t",f"{length:.3f}","-vf",vf,"-c:v","libx264","-preset","ultrafast","-crf",str(args.crf),"-c:a","aac","-b:a","128k","-ar","44100","-ac","2",str(clip)])
                clips.append(clip)
            listing=td/"concat.txt"; listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips))
            run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(listing),"-c","copy","-movflags","+faststart",str(out)])
        report={"source":str(src),"duration_seconds":total,"detected_scenes":len(scenes),"selected_clips":chosen,"method":"scene-change + approximate frame-difference motion score"}
        out.with_suffix(".analysis.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print("اكتمل:",out); return 0
    except Exception as e: print("فشل:",e); return 1

if __name__=="__main__": sys.exit(main())
