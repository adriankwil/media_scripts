import sys
import json
import subprocess
import argparse
import os
import re


def format_bytes(bytes:int, dp:int=2) -> list:
  '''
  Convert int number of bytes into human readable format with automatic units
  '''
  units = ["B", "KB", "MB", "GB"]
  u = 0
  while (bytes >= 1024):
    bytes = bytes/1024
    u+=1
  return f"{round(bytes, dp)}{units[u]}"


def match_key(parent_key: str, match_string: str) -> str:
  '''
  Find a regex match for a JSON key whose parent is 'parent_key' and return that key's value
  '''
  regex = re.compile(rf".*{match_string}.*")
  for k in parent_key:
    if regex.match(k):
      if DEBUG: print(f"found match: {k}")
      return parent_key.get(k)


def probe_file(file: str):
  '''
  Get file stream information using ffprobe in JSON format.
  '''
  cmd = f"ffprobe -v quiet -print_format json -show_format -show_streams \"{file}\""
  if DEBUG: print(f"cmd : {cmd}")
  raw = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True).stdout
  if DEBUG: print(f"raw ffprobe output:\n{raw}")
  info = json.loads(raw)

  return info


def replace_audio_names(name:str) -> str:
  '''
  Convert ffmpeg output to be more human readable. Used primarily for printing out the track list.
  '''
  if "truehd" in name.lower() and "atmos" in name.lower():
    return "THD Atmos"
  elif "truehd" in name.lower():
    return "TrueHD"
  elif "dolby digital plus + dolby atmos" == name.lower():
    return "DD+ Atmos"
  else:
    return name


def parse_ac(ac: int) -> str:
    '''
    Convert the raw number of channels into human readable format.
    eg: 2 becomes 2.0 and 6 becomes 5.1

    '''
    if ac == 0:
      return "  "
    elif ac > 2:
      return f"{ac-1}.1"
    else:
      return F"{ac}.0"


def gen_cmd(infile):
  '''
  Generate the bash commands to be run.
  This follows the general format:
  1) append '.original' to the original file
  2) use ffmpeg to create a new file with an added TrueHD track from the first DTS-HD MA track.
  3) OPTIONALLY and by default delete the original file
  '''
  info = probe_file(infile)
  streams = info.get("streams")

  # print header
  file_summary = []
  header = f"index\t{'type'.ljust(10)}\tlang\tsize"
  file_summary.append(header)
  if DEBUG: print("header: ", header)

  dts_hd_ma_stream = None
  has_truehd = False
  video_stream_index = None

  for s in streams:
    index = s.get("index")
    typ = s.get("codec_type")
    tags = s.get("tags")
    if not tags:
      if DEBUG: print(f"\"tags\" key doesnt exist, skipping this stream")
      continue

    size_bytes = match_key(tags, "NUMBER_OF_BYTES")
    if not size_bytes:
      if DEBUG: print(f"No \"NUMBER_OF_BYTES\" tag found, will try to calculate size from bit rate*time")
      duration = s.get("duration")
      bit_rate = s.get("bit_rate")
      if DEBUG: print(F"duration: {duration}, bit_rate: {bit_rate}")
      if duration and bit_rate:
        size_bytes = (float(duration)*int(bit_rate))/8
      else:
        if DEBUG: print(f"No \"NUMBER_OF_BYTES\" tag found and unable to calculate from rate*time. Using 0.")
        size_bytes = 0
    else:
      size_bytes = int(size_bytes)

    lang = tags.get("language") if typ != "video" else "-"
    profile = s.get("profile") or s.get("codec_name")
    ac = s.get("channels") if typ == "audio" else 0
    size = format_bytes(size_bytes)
    name = replace_audio_names(profile) if typ == "audio" else typ
    audio_channels = parse_ac(ac)

    stream_summary = f"{index}\t{name.ljust(10)}{audio_channels}\t{lang}\t{size.ljust(10)}"
    file_summary.append(stream_summary)
    if DEBUG: print(stream_summary)

    if typ == "video" and video_stream_index is None:
        video_stream_index = index

    if typ == "audio":
        if profile == 'DTS-HD MA' and dts_hd_ma_stream is None:
            dts_hd_ma_stream = s
        if 'truehd' in (profile or "").lower():
            has_truehd = True

  if not dts_hd_ma_stream or has_truehd:
      if DEBUG:
          if not dts_hd_ma_stream: print("No DTS-HD MA track found for conversion.")
          if has_truehd: print("File already contains a TrueHD track.")
      return [None, file_summary]

  dts_index = dts_hd_ma_stream.get("index")

  # Build the ffmpeg command
  cmd   =   f"mv \"{infile}\" \"{infile}.original\""
  cmd   +=  f" && ffmpeg -hide_banner -loglevel error -stats -i \"{infile}.original\""
  # Map streams in the desired order
  # 1. Video stream
  if video_stream_index is not None:
      cmd += f" -map 0:{video_stream_index}"
  # 2. The DTS-HD MA stream that will be converted to TrueHD
  cmd   +=  f" -map 0:{dts_index}"
  # 3. All original audio streams
  cmd   +=  f" -map 0:a"
  # 4. All original subtitle streams
  cmd   +=  f" -map 0:s?"
  # Copy all streams except the new audio track
  cmd   +=  f" -c copy"
  # Convert the first mapped audio stream (our new track) to TrueHD
  cmd   +=  f" -c:a:0 truehd -ac 6 -strict -2 -metadata:s:a:0 title=\"TrueHD 5.1\""
  # Set the new TrueHD track as the default audio stream
  cmd   +=  f" -disposition:a:0 default"
  # Set the original default audio stream to not be default anymore
  cmd   +=  f" -disposition:a:1 0"
  cmd   +=  f" \"{infile}\""
  cmd   +=  f" && touch -r \"{infile}.original\" \"{infile}\""
  if not NODEL: cmd +=  f" && rm \"{infile}.original\""

  return [cmd, file_summary]


def get_files(path):
  extensions = ["mkv", "mp4"]
  raw_list = []
  for e in extensions:
    cmd = ["find", f"{path}", "-type", "f", "-name", f"*.{e}"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, text=True).stdout
    raw_list += raw.split("\n")
  raw_list = list(filter(None, raw_list)) # remove empty items
  if DEBUG:
    print(len(raw_list))
    print(raw_list)
  to_remove = []
  for item in raw_list:
    if DEBUG: print(item)
    split = item.split("/")
    if "._" in split[-1]:
      if DEBUG: print(f"\t removing {item}")
      to_remove.append(item)

  if DEBUG:
    print(len(raw_list))
    print(raw_list)
  for tr in to_remove:
    raw_list.remove(tr)
  if DEBUG:
    print(len(raw_list))
    print(raw_list)

  return raw_list



if __name__ == '__main__':
  parser = argparse.ArgumentParser(prog='thd.py',
                                   description='Find movies that have DTS-HD MA as their default audio track and no TrueHD track present, and create a THD track from the DTS-HD MA track and set it as default.\nDEFAULT BEHVAIOUR is to DRY-RUN, making no changes.\nRequires ffmpeg installed, ideally version 7.1+ for good TrueHD compatibility (libavcodec 61.19.101 has been used for development)', formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('filepaths',
                      nargs='+',
                      help='One or more files or folders to target')
  parser.add_argument('--run',
                      action='store_true',
                      help='Actually run the commands. Default is False and will just print the commands to be run ')
  parser.add_argument('--debug',
                      action='store_true',
                      help='Set this to give more info on whats going on. (quite verbose)')
  parser.add_argument('--nodel',
                      action='store_true',
                      help='Set this to not delete the original video and just keep it with a .original appendix')
  args = parser.parse_args()
  FILEPATHS = args.filepaths
  EXECUTE   = args.run
  DEBUG     = args.debug
  NODEL     = args.nodel

  if not EXECUTE:
    print("\nDRYRUN - NO CHANGES WILL BE MADE. ADD '--run' TO MAKE CHANGES\n")
  else:
    print("Attempting to generate TrueHD audio tracks from DTS-HD MA.")

  files = []
  for path in FILEPATHS:
      abs_path = os.path.abspath(path)
      if os.path.isdir(abs_path):
          print("Searching for video files in", abs_path, "(recursive)")
          files.extend(get_files(abs_path))
      elif os.path.isfile(abs_path):
          files.append(abs_path)
      else:
          print(f"Warning: Path '{path}' is not a valid file or directory. Skipping.")

  # Remove duplicates that might occur if a file and its parent folder are both specified
  files = sorted(list(set(files)))

  if len(files) > 0:
      print(f"\nFound {len(files)} video file(s) to process:")
      for f in files:
          print(f)
  else:
      print("Found no video file(s) to process.")


  print()
  modified_files = []
  for infile in files:
    if DEBUG: print("infile : ", infile)
    cmd, file_summary = gen_cmd(infile)
    if cmd is not None:
      modified_files.append(infile)
      print("\n--------------------------------------------------------------------------------")
      print(f"File to modify: {infile}")
      for fs in file_summary:
        print(fs)
      out_line = f"A new TrueHD 5.1 track will be created and set as default."
      print(out_line)
      print("-"*len(out_line))
      print(cmd, "\n")
      if EXECUTE:
        subprocess.run(cmd, shell=True)

  if not modified_files:
    print("No files required modification.")
  else:
    print("\nSummary of files to be modified:")
    for f in modified_files:
      print(f)
    action = "modified" if EXECUTE else "to be modified"
    print(f"\nTotal files {action}: {len(modified_files)}")

