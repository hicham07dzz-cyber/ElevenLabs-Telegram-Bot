#!/usr/bin/env python3
"""AUTOFOX EDIT: local automatic highlight montage powered by FFmpeg."""
import argparse, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

def run(cmd, capture=False):
    try:
        return subprocess.run(cmd, check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None)
    except FileNotFoundError:
        raise RuntimeError("FFmpeg غير موجود. ثبّته: pkg install ffmpeg")
    except subprocess.CalledProcessError as e:
        raise RuntimeError((e.stderr or "FFmpeg failed")[-2200:])

def duration_of(path):
    p=run(["ffprobe","-v","error","-show_entries","format=duration",
           "-of","default=noprint_wrappers=1:nokey=1",str(path)],True)
    return float(p.stdout.strip())

def detect_scenes(path, threshold):
    p=run(["ffmpeg","-hide_banner","-i",str(path),"-vf",
           f"select='gt(scene,{threshold/100:.3f})',showinfo",
           "-an","-f","null","-"],True)
    times=[float(x) for x in re.findall(r"pts_time:([0-9.]+)",p.stderr or "")]
    total=duration_of(path)
    cuts=[0.0]+sorted(set(t for t in times if 0<t<total))+[total]
    scenes=[(a,b) for a,b in zip(cuts,cuts[1:]) if b-a>=0.8]
    return scenes or [(0,total)]

def motion_score(path,a,b):
    p=subprocess.run(["ffmpeg","-v","error","-ss",f"{a:.3f}","-i",str(path),
        "-t",f"{max(.3,b-a):.3f}","-vf","fps=2,scale=80:45,format=gray",
        "-f","rawvideo","-"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    size=80*45; raw=p.stdout; count=len(raw)//size
    if count<2: return 0.0
    total=0
    for i in range(1,count):
        prev=raw[(i-1)*size:i*size]; cur=raw[i*size:(i+1)*size]
        total += sum(abs(x-y) for x,y in zip(prev,cur))/size
    return total/(count-1)

def audio_score(path,a,b):
    p=subprocess.run(["ffmpeg","-hide_banner","-nostats","-ss",f"{a:.3f}",
        "-i",str(path),"-t",f"{max(.3,b-a):.3f}","-vn","-af","volumedetect",
        "-f","null","-"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    m=re.search(r"mean_volume:\s*(-?[0-9.]+) dB",p.stderr or "")
    if not m: return 0.0
    # Map typical quiet-to-loud audio into a bounded score.
    return max(0.0,min(1.0,(float(m.group(1))+45)/45))

def render(args):
    src=Path(args.video).expanduser()
    if not src.is_file(): raise RuntimeError(f"لم أجد ملف الفيديو: {src}")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ثبّت FFmpeg: pkg install ffmpeg")
    total=duration_of(src)
    print(f"مدة الفيديو: {total:.1f} ثانية")
    print("1/4 اكتشاف تغيّر المشاهد...")
    scenes=detect_scenes(src,args.threshold)
    print(f"المشاهد المرصودة: {len(scenes)}")
    print("2/4 تقييم الحركة ومستوى الصوت...")
    scored=[]
    for i,(a,b) in enumerate(scenes):
        motion=motion_score(src,a,b)
        audio=audio_score(src,a,b)
        scored.append({"index":i+1,"start":a,"end":b,"duration":b-a,
                       "motion_score":round(motion,2),"audio_score":round(audio,3),
                       "rank_score":round(motion*0.75+audio*12,3)})
    chosen=[]; used=0.0
    for item in sorted(scored,key=lambda x:x["rank_score"],reverse=True):
        length=min(item["duration"],args.max_clip)
        if used+length>max(5,args.seconds) and chosen: continue
        chosen.append(item); used+=length
        if used>=max(5,args.seconds): break
    chosen.sort(key=lambda x:x["start"])
    if not chosen: raise RuntimeError("لم يتم العثور على لقطات مناسبة.")
    out=Path(args.output).expanduser() if args.output else src.with_name(src.stem+"_AUTOFOX.mp4")
    if src.resolve()==out.resolve(): raise RuntimeError("مسار الإخراج يجب أن يختلف عن الأصل.")
    out.parent.mkdir(parents=True,exist_ok=True)
    if args.aspect=="vertical":
        w,h=720,1280
        vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,format=yuv420p"
    elif args.aspect=="square":
        w,h=720,720
        vf=f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,format=yuv420p"
    else:
        w,h=1280,720
        vf=f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"
    print("3/4 تركيب اللقطات...")
    with tempfile.TemporaryDirectory(prefix="autofox_") as td:
        td=Path(td); clips=[]
        for n,item in enumerate(chosen,1):
            length=min(item["duration"],args.max_clip)
            start=item["start"]+max(0,(item["duration"]-length)/2)
            clip=td/f"clip_{n:03}.mp4"
            run(["ffmpeg","-y","-v","error","-ss",f"{start:.3f}","-i",str(src),
                 "-t",f"{length:.3f}","-vf",vf,"-c:v","libx264","-preset","ultrafast",
                 "-crf","24","-c:a","aac","-b:a","128k","-ar","44100","-ac","2",str(clip)])
            clips.append(clip)
        listing=td/"concat.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips))
        assembled=td/"assembled.mp4"
        run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(listing),
             "-c","copy","-movflags","+faststart",str(assembled)])
        music=Path(args.music).expanduser() if args.music else None
        if music:
            if not music.is_file(): raise RuntimeError("ملف الموسيقى غير موجود.")
            print("إضافة الموسيقى المختارة...")
            run(["ffmpeg","-y","-v","error","-i",str(assembled),"-stream_loop","-1","-i",str(music),
                 "-map","0:v:0","-map","1:a:0","-t",f"{used:.3f}",
                 "-c:v","copy","-c:a","aac","-b:a","192k","-af","volume=0.22,afade=t=out:st="+str(max(0,used-2)) + ":d=2",
                 "-movflags","+faststart",str(out)])
        else:
            shutil.copy2(assembled,out)
    report={"source":str(src),"duration_seconds":total,"detected_scenes":len(scenes),
        "selected_clips":chosen,"output_seconds":round(used,2),
        "aspect":args.aspect,"music_added":bool(args.music),
        "method":"FFmpeg scene-change + frame-difference motion + audio loudness heuristic",
        "limitations":"لا يتعرف هذا الإصدار دلالياً على Headshot أو Kill أو محتوى الكلام."}
    out.with_suffix(".analysis.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print("4/4 اكتمل المونتاج:",out)

def main():
    ap=argparse.ArgumentParser(description="AUTOFOX EDIT — مونتاج تلقائي")
    ap.add_argument("video"); ap.add_argument("--output"); ap.add_argument("--music")
    ap.add_argument("--seconds",type=float,default=30); ap.add_argument("--max-clip",type=float,default=5)
    ap.add_argument("--threshold",type=float,default=27); ap.add_argument("--aspect",choices=["original","vertical","square"],default="original")
    args=ap.parse_args()
    try: render(args); return 0
    except Exception as e: print("فشل:",e); return 1

if __name__=="__main__": sys.exit(main())
