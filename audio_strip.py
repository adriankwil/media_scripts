import sys
import json
import subprocess
import argparse
import os
import re


def format_bytes(bytes):
  units = ["B", "KB", "MB", "GB"]
  u = 0
  while (bytes >= 1024):
    bytes = bytes/1024
    u+=1
  return f"{round(bytes, 2)}{units[u]}"

def match_key(parent_key, match_string):
  regex = re.compile(rf".*{match_string}.*")
  for k in parent_key:
    if regex.match(k):
      if DEBUG: print(f"found match: {k}")
      return parent_key.get(k)

def gen_cmd(infile):
  cmd = [
      "ffprobe", "-v", "quiet",
      "-print_format", "json",
      "-show_format", "-show_streams",
      infile
  ]
  raw = subprocess.run(cmd, stdout=subprocess.PIPE, text=True).stdout
  info = json.loads(raw)
  streams = info.get("streams")

  if DEBUG:
    print(f"raw ffprobe output:\n{raw}")

  # print header
  file_summary = []
  header = f"index\ttype\tlang\tsize"
  file_summary.append(header)
  if DEBUG: print("header: ", header)

  unwanted_indexes = []
  total_saved = 0
  for s in streams:
    #if DEBUG: print(s)
    rem = ""
    index = s.get("index")
    typ = s.get("codec_type")
    tags = s.get("tags")
    if not tags:
      if DEBUG: print(f"\"tags\" key doesnt exist, skipping this stream")
      continue

    size_bytes = match_key(tags, "NUMBER_OF_BYTES")
    if not size_bytes:
      if DEBUG: print(f"No \"NUMBER_OF_BYTES\" tag found, using 0")
      size_bytes = 0
      pass
    else:
      size_bytes = int(size_bytes)

    if typ!="video":
      lang = tags.get("language")
    else:
      lang = "-"


    size = format_bytes(size_bytes)

    if (typ=="audio" or typ=="subtitle") and (lang not in LANGUAGES):
      rem = "<-remove"
      unwanted_indexes.append(index)
      total_saved += size_bytes

    stream_summary = f"{index}\t{typ[0]}\t{lang}\t{size.ljust(10)}{rem}"
    file_summary.append(stream_summary)
    if DEBUG: print(stream_summary)


  removal = ""
  for i in unwanted_indexes:
    removal = removal + f"-map -0:{i} "

  non_eng_streams = len(unwanted_indexes)
  if non_eng_streams == 0:
    if DEBUG: print("No unwanted audio or sub streams in this file.")
    return [None,None,None]
  else:
    if DEBUG: print(f"\nFound {non_eng_streams} non english audio/sub streams with indexes: {unwanted_indexes}\n")
    cmd =   f"mv '{infile}' '{infile}.original'"
    cmd +=  f" && ffmpeg -hide_banner -loglevel error -stats -i '{infile}.original' -map 0 {removal} -c copy '{infile}'"
    cmd +=  f" && touch -r '{infile}.original' '{infile}'"
    if not NODEL: cmd +=  f" && rm '{infile}.original'"
    return [cmd, total_saved, file_summary]


def get_files(path):
  cmd = ["find", f"{path}", "-type", "f", "-name", "*.mkv"]
  raw = subprocess.run(cmd, stdout=subprocess.PIPE, text=True).stdout
  raw_list = raw.split("\n")
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
  def comma_separated_list(value: str) -> list[str]:
    """Turn 'eng,pol' into ['eng', 'pol'] (stripping spaces, ignoring empties)."""
    return [v.strip() for v in value.split(',') if v.strip()]

  parser = argparse.ArgumentParser(prog='audio_strip.py',
                                   description='Remove all unwanted language audio tracks from video files to save space.')
  parser.add_argument('filepath',
                      help='File or Folder to target')
  parser.add_argument('-l',
                      '--languages',
                      type=comma_separated_list,
                      default=['eng'],
                      help='Languages to keep. Default is eng')
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
  FILEPATH  = os.path.abspath(args.filepath)
  LANGUAGES = args.languages
  EXECUTE   = args.run
  DEBUG     = args.debug
  NODEL     = args.nodel


  if not EXECUTE:
    print("DRYRUN - NO CHANGES WILL BE MADE. ADD '--run' TO MAKE CHANGES\n")
  print("Removing all languages other than: ", end="")
  for i,l in enumerate(LANGUAGES):
    print(l, end="")
    if i<len(LANGUAGES)-1:
      print(",", end="")
  print()

  if os.path.isdir(FILEPATH):
    files = get_files(FILEPATH)
    print("Working on all .mkv files in", FILEPATH, "(recursive)")
    if len(files)>0:
      print(f"Found {len(files)} .mkv files:")
      for f in files: print(f)
    else:
      print("Found no .mkv file(s) in this dir")
  elif os.path.isfile(FILEPATH):
    files = [FILEPATH]
    print("Working on", FILEPATH)

  print()
  total_space_saved = 0
  breakdown = []
  for infile in files:
    if DEBUG: print("infile : ", infile)
    cmd,saveable_space,file_summary = gen_cmd(infile)
    if cmd is not None:
      saveable_space_formatted = format_bytes(saveable_space)
      breakdown.append([infile, saveable_space_formatted, saveable_space])
      total_space_saved += saveable_space
      print("\n--------------------------------------------------------------------------------")
      for fs in file_summary:
        print(fs)
      out_line = f"Space to save: {saveable_space_formatted}"
      print(out_line)
      print("-"*len(out_line))
      print(cmd, "\n")
      if EXECUTE:
        subprocess.run(cmd, shell=True)

  if total_space_saved == 0:
    print("No files needed thinning")
  else:
    breakdown = sorted(breakdown, key=lambda item: item[-1])
    for b in breakdown:
      print(f"{b[1].ljust(10)} : {b[0].split('/')[-1]}")
    if EXECUTE:
      print(f"\nTotal Space Saved : {format_bytes(total_space_saved)}")
    else:
      print(f"\nTotal saveable space : {format_bytes(total_space_saved)}")
