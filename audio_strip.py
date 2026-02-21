import sys
import json
import subprocess
import argparse
import os
import re


def format_bytes(size: int, dp: int = 2) -> str:
  '''
  Convert int number of bytes into human readable format with automatic units
  '''
  units = ["B", "KB", "MB", "GB"]
  u = 0
  while size >= 1024:
    size = size / 1024
    u += 1
  return f"{round(size, dp)}{units[u]}"


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
  cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file]
  if DEBUG: print(f"cmd : {cmd}")
  raw = subprocess.run(cmd, stdout=subprocess.PIPE, text=True).stdout
  if DEBUG: print(f"raw ffprobe output:\n{raw}")
  return json.loads(raw)


def replace_audio_names(name: str) -> str:
  '''
  Convert ffmpeg output to be more human readable. Used primarily for printing out the track list.
  '''
  lower = name.lower()
  if "truehd" in lower and "atmos" in lower:
    return "THD Atmos"
  elif "truehd" in lower:
    return "TrueHD"
  elif lower == "dolby digital plus + dolby atmos":
    return "DD+ Atmos"
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
  return f"{ac}.0"


def gen_cmd(infile):
  '''
  Generate the bash commands to be run.
  This follows the general format:
  1) append '.original' to the original file
  2) use ffmpeg to delete the unwanted audio tracks
  2.1) OPTIONALLY copy the first audio track to a TrueHD 5.1 stream if it is DTS HD-MA.
  3) OPTIONALLY and by default delete the original file
  '''
  info = probe_file(infile)
  streams = info.get("streams")

  # Find the language of the first audio track
  first_audio_lang = None
  for s in streams:
    if s.get("codec_type") == "audio":
      tags = s.get("tags")
      if tags and tags.get("language"):
        first_audio_lang = tags.get("language")
        if DEBUG: print(f"Detected first audio track language: {first_audio_lang}")
        break

  # Create a set of languages to keep for audio tracks
  audio_languages_to_keep = set(LANGUAGES)
  if first_audio_lang:
    audio_languages_to_keep.add(first_audio_lang)

  if DEBUG:
    print(f"Languages to keep for audio: {list(audio_languages_to_keep)}")
    print(f"Languages to keep for subtitles: {LANGUAGES}")

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
      if DEBUG: print(f"duration: {duration}, bit_rate: {bit_rate}")
      if duration and bit_rate:
        size_bytes = (float(duration) * int(bit_rate)) / 8
      else:
        if DEBUG: print(f"No \"NUMBER_OF_BYTES\" tag found and unable to calculate from rate*time. Using 0.")
        size_bytes = 0
    else:
      size_bytes = int(size_bytes)

    if typ != "video":
      lang = tags.get("language")
    else:
      lang = "-"

    if typ == "audio":
      ca = s.get("profile") or s.get("codec_name")
      ac = s.get("channels")
    else:
      ca, ac = "-", 0

    size = format_bytes(size_bytes)

    # Determine if the stream should be removed
    remove_stream = False
    if typ == "audio" and lang not in audio_languages_to_keep:
      remove_stream = True
    elif typ == "subtitle" and lang not in LANGUAGES:
      remove_stream = True

    if remove_stream:
      rem = "<-remove"
      unwanted_indexes.append(index)
      total_saved += size_bytes
    else:
      rem = ""
      wanted_indexes.append([index, ca])
      total_kept += size_bytes

    if DEBUG: print(typ)

    # replace the typ string with the audio stream profile just for audio streams
    name = replace_audio_names(ca) if typ == "audio" else typ

    if DEBUG: print(name)
    audio_channels = parse_ac(ac)
    stream_summary = f"{index}\t{name.ljust(10)}{audio_channels}\t{lang}\t{size.ljust(10)}{rem}"
    file_summary.append(stream_summary)
    if DEBUG: print(stream_summary)

  if DEBUG: print(f"unwanted_indexes : {unwanted_indexes}")
  if DEBUG: print(f"wanted_indexes : {wanted_indexes}")

  removal = " ".join(f"-map -0:{i}" for i in unwanted_indexes)
  # wanted_indexes[0] is the video stream, which is handled by -map 0:0
  # so we only need to map the other wanted streams
  keep = " ".join(f"-map 0:{i}" for i, name in wanted_indexes[1:])

  non_eng_streams = len(unwanted_indexes)
  # Check if there are any streams to remove OR if THD conversion is requested
  is_dtshd_ma = THD and len(wanted_indexes) > 1 and 'DTS-HD MA' in wanted_indexes[1][1]
  if non_eng_streams == 0 and not is_dtshd_ma:
    if DEBUG: print("No unwanted streams in this file and DTSHDMA->THD conversion is not applicable/enabled.")
    return [None, None, None, None, None]

  if DEBUG: print(f"\nFound {non_eng_streams} unwanted audio/sub streams with indexes: {unwanted_indexes}\n")

  original = f"{infile}.original"
  cmd = f"mv \"{infile}\" \"{original}\""
  cmd += f" && ffmpeg -hide_banner -loglevel error -stats -i \"{original}\" -map 0:0"
  if is_dtshd_ma:
    # Map the DTS-HD MA stream first for conversion
    cmd += f" -map 0:{wanted_indexes[1][0]}"
  if keep:
    cmd += f" {keep}"
  if removal:
    cmd += f" {removal}"
  cmd += f" -c copy"
  if is_dtshd_ma:
    # Apply conversion to the first audio stream in the output (which is now the DTS-HD MA stream)
    cmd += f" -c:a:0 truehd -ac 6 -strict -2 -metadata:s:a:0 Title=\"TrueHD 5.1\""
  cmd += f" \"{infile}\""
  # set the new file timestamp to match the original file
  cmd += f" && touch -r \"{original}\" \"{infile}\""
  if not NODEL:
    cmd += f" && rm \"{original}\""

  return [cmd, total_saved, total_kept, file_summary, sorted(list(audio_languages_to_keep))]


def get_files(path):
  '''
  Get all movie files in a given directory
  '''
  extensions = {".mkv", ".mp4"}
  results = []
  for root, dirs, filenames in os.walk(path):
    for name in filenames:
      if name.startswith("._"):
        continue
      ext = os.path.splitext(name)[1].lower()
      if ext in extensions:
        results.append(os.path.join(root, name))

  if DEBUG:
    print(len(results))
    print(results)
  return results


if __name__ == '__main__':
  def comma_separated_list(value: str) -> list[str]:
    """Turn 'eng,pol' into ['eng', 'pol'] (stripping spaces, ignoring empties)."""
    return [v.strip() for v in value.split(',') if v.strip()]

  parser = argparse.ArgumentParser(prog='audio_strip.py',
                                   description='Remove all unwanted language audio tracks from video files to save space.\nDEFAULT BEHVAIOUR is to DRY-RUN, making no changes.\nRequires ffmpeg installed, ideally version 7.1+ for good TrueHD compatibility (libavcodec 61.19.101 has been used for development)', formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('filepaths',
                      nargs='+',
                      help='One or more files or folders to target')
  parser.add_argument('-l',
                      '--languages',
                      type=comma_separated_list,
                      default=['eng'],
                      help='Languages to keep for subtitles. Audio tracks for these languages will also be kept, in addition to the language of the first audio track. Default is eng')
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
  FILEPATHS = args.filepaths
  LANGUAGES = args.languages
  EXECUTE   = args.run
  DEBUG     = args.debug
  NODEL     = args.nodel
  THD       = args.thd

  if not EXECUTE:
    print("\nDRYRUN - NO CHANGES WILL BE MADE. ADD '--run' TO MAKE CHANGES\n")
    print("Would remove all subtitle languages other than: ", ", ".join(LANGUAGES))
    print("Would also keep audio tracks matching the first audio track's language.")
  else:
    print("Processing files...")
    if THD:
      print("Generate TrueHD audio track from DTS-HD MA and make it the first track if applicable.")

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
  files = sorted(set(files))

  if files:
    print(f"\nFound {len(files)} video file(s) to process:")
    for f in files:
      print(f)
  else:
    print("Found no video file(s) to process.")

  print()
  total_bytes_saved = 0
  breakdown = []
  MIN_SAVE_BYTES = 100 * 1024 * 1024  # 100 MB
  for infile in files:
    if DEBUG: print("infile : ", infile)
    cmd, saveable_bytes, kept_bytes, file_summary, langs_kept = gen_cmd(infile)
    if cmd is not None:
      total_bytes = saveable_bytes + kept_bytes
      saveable_space = format_bytes(saveable_bytes)
      total_file_size = format_bytes(total_bytes)
      percent_saved = int((saveable_bytes / total_bytes) * 100) if total_bytes else 0

      if saveable_bytes < MIN_SAVE_BYTES:
        if DEBUG: print(f"Saveable space {saveable_space} is less than 100MB. Skipping {infile.split('/')[-1]}")
        continue

      breakdown.append([infile, saveable_space, saveable_bytes, percent_saved, total_file_size])
      total_bytes_saved += saveable_bytes
      print("\n--------------------------------------------------------------------------------")
      print(f"Keeping languages: {', '.join(langs_kept)}")
      for fs in file_summary:
        print(fs)
      out_line = f"Space to save: {saveable_space}.  ({percent_saved}% of {total_file_size})"
      print(out_line)
      print("-" * len(out_line))
      print(cmd, "\n")
      if EXECUTE:
        subprocess.run(cmd, shell=True)
        print("Done\n")

  if total_bytes_saved == 0:
    print("No files needed thinning")
  else:
    breakdown = sorted(breakdown, key=lambda item: item[2])
    for b in breakdown:
      saved = f"{b[1]}"
      percent = f"({b[3]}% of {b[4]})"
      print(f"{saved.ljust(10)} {percent.ljust(17)} : {b[0].split('/')[-1]}")
    if EXECUTE:
      print(f"\nTotal Space Saved : {format_bytes(total_bytes_saved)}")
    else:
      print(f"\nTotal saveable space : {format_bytes(total_bytes_saved)}")
