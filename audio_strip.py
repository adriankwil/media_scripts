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
  cmd = f"ffprobe -v quiet -print_format json -show_format -show_streams '{file}'"
  if DEBUG: print(f"cmd : {cmd}")
  raw = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True).stdout
  if DEBUG: print(f"raw ffprobe output:\n{raw}")  # raw = subprocess.run(cmd, stdout=subprocess.PIPE, text=True).stdout
  info = json.loads(raw)

  return info


def replace_audio_names(name:str) -> str:
  if "truehd" in name.lower() and "atmos" in name.lower():
    return "Atmos THD"
  elif "truehd" in name.lower():
    return "TrueHD"
  else:
    return name


def gen_cmd(infile):
  '''
  Generate the bash commands to be run.
  This follows the general format:
  1) append '.original' to the original file
  2) use ffmpeg to delete the unwanted audio tracks
  2.1) OPTIONALLY copy the first audio track to a TrueHD 5.1 stream if it is DTS HD-MA.
  3) OPTIONALLY and by defalt delete the original file
  '''
  info = probe_file(infile)
  streams = info.get("streams")


  # print header
  file_summary = []
  header = f"index\t{'type'.ljust(10)}\tlang\tsize"
  file_summary.append(header)
  if DEBUG: print("header: ", header)

  unwanted_indexes = []
  wanted_indexes = []
  total_saved = 0
  total_kept = 0
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

    if typ != "video":
      lang  = tags.get("language")
    else:
      lang = "-"

    if typ == "audio":
      ca    = s.get("profile")
      if ca == None:
        ca = s.get("codec_name")
      ac    = s.get("channels")
    else:
      ca,ac = "-",0

    size = format_bytes(size_bytes)

    if (typ=="audio" or typ=="subtitle") and (lang not in LANGUAGES):
      rem = "<-remove"
      unwanted_indexes.append(index)
      total_saved += size_bytes
    else:
      wanted_indexes.append([index, ca])
      total_kept += size_bytes

    if DEBUG:print(typ)

    # replace the typ string with the audio stream profile just for audio streams
    if typ=="audio":
      name = replace_audio_names(ca)
    else:
      name = typ


    if DEBUG:print(name)

    stream_summary = f"{index}\t{name.ljust(10)}\t{lang}\t{size.ljust(10)}{rem}"
    file_summary.append(stream_summary)
    if DEBUG: print(stream_summary)

  if DEBUG: print(f"unwanted_indexes : {unwanted_indexes}")
  if DEBUG: print(f"wanted_indexes : {wanted_indexes}")

  removal = ""
  for i in unwanted_indexes:
    removal = removal + f"-map -0:{i} "

  keep = ""
  for i,name in wanted_indexes[1:]:
    keep = keep + f"-map 0:{i} "

  non_eng_streams = len(unwanted_indexes)
  if non_eng_streams == 0:
    if DEBUG: print("No unwanted audio or sub streams in this file.")
    return [None,None,None]
  else:
    if DEBUG: print(f"\nFound {non_eng_streams} non english audio/sub streams with indexes: {unwanted_indexes}\n")
    cmd   =   f"mv '{infile}' '{infile}.original'"
    cmd   +=  f" && ffmpeg -hide_banner -loglevel error -stats -i '{infile}.original' -map 0:0"
    if THD and (wanted_indexes[1][1] == 'DTS-HD MA'):
      cmd +=  f" -map 0:{wanted_indexes[1][0]}"
    cmd   +=  f" {keep} -c copy"
    if THD and (wanted_indexes[1][1] == 'DTS-HD MA'):
      cmd +=  f" -c:a:0 truehd -ac 6 -strict -2 -metadata:s:a:0 Title='TrueHD 5.1'"
    cmd   +=  f" '{infile}'"
    cmd   +=  f" && touch -r '{infile}.original' '{infile}'"
    if not NODEL: cmd +=  f" && rm '{infile}.original'"
    return [cmd, total_saved, total_kept, file_summary]


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
                                   description='Remove all unwanted language audio tracks from video files to save space.\nDEFAULT BEHVAIOUR is to DRY-RUN, making no changes.\nRequires ffmpeg installed, ideally version 7.1+ for good TrueHD compatibility (libavcodec 61.19.101 has been used for development)', formatter_class=argparse.RawTextHelpFormatter)
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
  parser.add_argument('--thd',
                      action='store_true',
                      help='Set this to check if the first audio track is DTSHD-MA and convert it to be TrueHD 5.1, and set it as the first audio track')
  args = parser.parse_args()
  FILEPATH  = os.path.abspath(args.filepath)
  LANGUAGES = args.languages
  EXECUTE   = args.run
  DEBUG     = args.debug
  NODEL     = args.nodel
  THD       = args.thd


  if not EXECUTE:
    print("\nDRYRUN - NO CHANGES WILL BE MADE. ADD '--run' TO MAKE CHANGES\n")
    print("Would remove all languages other than: ", end="")
  else:
    print("Removing all languages other than: ", end="")
  print(*LANGUAGES, sep=", ")

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
  total_bytes_saved = 0
  breakdown = []
  for infile in files:
    if DEBUG: print("infile : ", infile)
    cmd,saveable_bytes,kept_bytes,file_summary = gen_cmd(infile)
    if cmd is not None:
      saveable_space = format_bytes(saveable_bytes)
      breakdown.append([infile, saveable_space, saveable_bytes])
      total_bytes_saved += saveable_bytes
      print("\n--------------------------------------------------------------------------------")
      for fs in file_summary:
        print(fs)
      total_bytes = saveable_bytes+kept_bytes
      total_file_size = format_bytes(total_bytes)
      percent_saved = f"{(saveable_bytes/total_bytes)*100}"
      out_line = f"Space to save: {saveable_space}. {percent_saved}% of {total_file_size}"
      print(out_line)
      print("-"*len(out_line))
      print(cmd, "\n")
      if EXECUTE:
        subprocess.run(cmd, shell=True)

  if total_bytes_saved == 0:
    print("No files needed thinning")
  else:
    breakdown = sorted(breakdown, key=lambda item: item[-1])
    for b in breakdown:
      print(f"{b[1].ljust(10)} : {b[0].split('/')[-1]}")
    if EXECUTE:
      print(f"\nTotal Space Saved : {format_bytes(total_bytes_saved)}")
    else:
      print(f"\nTotal saveable space : {format_bytes(total_bytes_saved)}")
