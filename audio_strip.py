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

  # Create a set of languages to keep for audio tracks
  audio_languages_to_keep = set(LANGUAGES)
  if not LANGUAGES_EXPLICIT:
    # Auto-detect: also keep the first audio track's language
    for s in streams:
      if s.get("codec_type") == "audio":
        tags = s.get("tags")
        if tags and tags.get("language"):
          first_audio_lang = tags.get("language")
          if DEBUG: print(f"Detected first audio track language: {first_audio_lang}")
          audio_languages_to_keep.add(first_audio_lang)
          break

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

  # Determine DTS-HD MA conversion status before filtering
  is_dtshd_ma = THD and len(wanted_indexes) > 1 and 'DTS-HD MA' in wanted_indexes[1][1]

  # Calculate the size of the new TrueHD stream (assumed same as the DTS-HD MA source)
  thd_added_bytes = 0
  if is_dtshd_ma:
    thd_stream = next(s for s in streams if s.get("index") == wanted_indexes[1][0])
    thd_tags = thd_stream.get("tags", {})
    thd_size = match_key(thd_tags, "NUMBER_OF_BYTES") if thd_tags else None
    if thd_size:
      thd_added_bytes = int(thd_size)
    else:
      duration = thd_stream.get("duration")
      bit_rate = thd_stream.get("bit_rate")
      thd_added_bytes = int((float(duration) * int(bit_rate)) / 8) if duration and bit_rate else 0

  # Keep only the necessary audio streams, move excess audio to unwanted.
  # In THD conversion case, the kept stream is mapped twice (THD conversion + original copy).
  wanted_audio = []
  for idx_pair in wanted_indexes:
    stream = next((s for s in streams if s.get("index") == idx_pair[0]), None)
    if stream and stream.get("codec_type") == "audio":
      wanted_audio.append(idx_pair)

  # Keep the first audio stream per language, plus all TrueHD and DTS-HD MA streams of kept languages
  seen_languages = set()
  excess_audio = []
  for i, idx_pair in enumerate(wanted_audio):
    stream = next(s for s in streams if s.get("index") == idx_pair[0])
    lang = stream.get("tags", {}).get("language")
    codec = idx_pair[1] or ""
    is_thd_or_dtshdma = "truehd" in codec.lower() or "DTS-HD MA" in codec
    if lang not in seen_languages:
      seen_languages.add(lang)
    elif not is_thd_or_dtshdma:
      excess_audio.append(idx_pair)

  for idx_pair in excess_audio:
    wanted_indexes.remove(idx_pair)
    unwanted_indexes.append(idx_pair[0])
    # Recalculate stream size for totals
    stream = next(s for s in streams if s.get("index") == idx_pair[0])
    tags = stream.get("tags", {})
    size_bytes = match_key(tags, "NUMBER_OF_BYTES") if tags else None
    if size_bytes:
      size_bytes = int(size_bytes)
    else:
      duration = stream.get("duration")
      bit_rate = stream.get("bit_rate")
      size_bytes = int((float(duration) * int(bit_rate)) / 8) if duration and bit_rate else 0
    total_saved += size_bytes
    total_kept -= size_bytes
    # Update summary line to mark as removed
    for i, line in enumerate(file_summary):
      if line.startswith(f"{idx_pair[0]}\t"):
        file_summary[i] = line + "<-remove"
        break

  if DEBUG: print(f"after audio filtering - unwanted: {unwanted_indexes}, wanted: {wanted_indexes}")

  # Final override: rescue any streams the user explicitly wants to keep
  if KEEP_INDEXES:
    for keep_idx in KEEP_INDEXES:
      if keep_idx in unwanted_indexes:
        unwanted_indexes.remove(keep_idx)
        stream = next((s for s in streams if s.get("index") == keep_idx), None)
        if stream:
          ca = stream.get("profile") or stream.get("codec_name") or "-"
          wanted_indexes.append([keep_idx, ca])
          tags = stream.get("tags", {})
          size_bytes = match_key(tags, "NUMBER_OF_BYTES") if tags else None
          if size_bytes:
            size_bytes = int(size_bytes)
          else:
            duration = stream.get("duration")
            bit_rate = stream.get("bit_rate")
            size_bytes = int((float(duration) * int(bit_rate)) / 8) if duration and bit_rate else 0
          total_saved -= size_bytes
          total_kept += size_bytes
          for i, line in enumerate(file_summary):
            if line.startswith(f"{keep_idx}\t") and "<-remove" in line:
              file_summary[i] = line.replace("<-remove", "<-keep(override)")
              break
    wanted_indexes.sort(key=lambda x: x[0])
    if DEBUG: print(f"after keep override - unwanted: {unwanted_indexes}, wanted: {wanted_indexes}")

  # Final override: force-remove any streams the user explicitly wants removed
  if REMOVE_INDEXES:
    for rem_idx in REMOVE_INDEXES:
      match = [pair for pair in wanted_indexes if pair[0] == rem_idx]
      if match:
        wanted_indexes.remove(match[0])
        unwanted_indexes.append(rem_idx)
        stream = next((s for s in streams if s.get("index") == rem_idx), None)
        if stream:
          tags = stream.get("tags", {})
          size_bytes = match_key(tags, "NUMBER_OF_BYTES") if tags else None
          if size_bytes:
            size_bytes = int(size_bytes)
          else:
            duration = stream.get("duration")
            bit_rate = stream.get("bit_rate")
            size_bytes = int((float(duration) * int(bit_rate)) / 8) if duration and bit_rate else 0
          total_saved += size_bytes
          total_kept -= size_bytes
          for i, line in enumerate(file_summary):
            if line.startswith(f"{rem_idx}\t") and "<-remove" not in line:
              file_summary[i] = line + "<-remove(override)"
              break
    if DEBUG: print(f"after remove override - unwanted: {unwanted_indexes}, wanted: {wanted_indexes}")

  # wanted_indexes[0] is the video stream, which is handled by -map 0:0
  # so we only need to map the other wanted streams
  keep = " ".join(f"-map 0:{i}" for i, name in wanted_indexes[1:])

  non_eng_streams = len(unwanted_indexes)
  # Check if there are any streams to remove OR if THD conversion is requested
  if non_eng_streams == 0 and not is_dtshd_ma:
    if DEBUG: print("No unwanted streams in this file and DTSHDMA->THD conversion is not applicable/enabled.")
    return [None, None, None, None, None, False, 0]

  if DEBUG: print(f"\nFound {non_eng_streams} unwanted audio/sub streams with indexes: {unwanted_indexes}\n")

  original = f"{infile}.original"
  cmd = f"mv \"{infile}\" \"{original}\""
  cmd += f" && ffmpeg -hide_banner -loglevel error -stats -i \"{original}\" -map 0:0"
  if is_dtshd_ma:
    # Map the DTS-HD MA stream first for conversion
    cmd += f" -map 0:{wanted_indexes[1][0]}"
  if keep:
    cmd += f" {keep}"
  cmd += f" -c copy"
  if is_dtshd_ma:
    # Apply conversion to the first audio stream in the output (which is now the DTS-HD MA stream)
    cmd += f" -c:a:0 truehd -ac 6 -strict -2 -metadata:s:a:0 Title=\"TrueHD 5.1\""
  cmd += f" \"{infile}\""
  # set the new file timestamp to match the original file
  cmd += f" && touch -r \"{original}\" \"{infile}\""
  if not NODEL:
    cmd += f" && rm \"{original}\""

  return [cmd, total_saved, total_kept, file_summary, sorted(list(audio_languages_to_keep)), is_dtshd_ma, thd_added_bytes]


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

  def comma_separated_ints(value: str) -> list[int]:
    """Turn '3,4' into [3, 4] (stripping spaces, ignoring empties)."""
    return [int(v.strip()) for v in value.split(',') if v.strip()]

  def parse_size(value: str) -> int:
    """Turn '500m' into bytes (500*1024*1024), '1g' into 1*1024*1024*1024, etc."""
    value = value.strip().lower()
    multipliers = {'b': 1, 'k': 1024, 'm': 1024**2, 'g': 1024**3}
    if value[-1] in multipliers:
      return int(float(value[:-1]) * multipliers[value[-1]])
    return int(value)

  parser = argparse.ArgumentParser(prog='audio_strip.py',
                                   description='Remove all unwanted language audio tracks from video files to save space.\nDEFAULT BEHVAIOUR is to DRY-RUN, making no changes.\nRequires ffmpeg installed, ideally version 7.1+ for good TrueHD compatibility (libavcodec 61.19.101 has been used for development)', formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('filepaths',
                      nargs='+',
                      help='One or more files or folders to target')
  parser.add_argument('-l',
                      '--languages',
                      type=comma_separated_list,
                      default=None,
                      help='Languages to keep. When explicitly given, applies to BOTH audio and subtitles with no auto-detection. When omitted, defaults to eng for subtitles and auto-detects the first audio track\'s language')
  parser.add_argument('--run',
                      action='store_true',
                      help='Actually run the commands. Default is False and will just print the commands to be run ')
  parser.add_argument('--debug',
                      action='store_true',
                      help='Set this to give more info on whats going on. (quite verbose)')
  parser.add_argument('--nodel',
                      action='store_true',
                      help='Set this to not delete the original video and just keep it with a .original appendix')
  parser.add_argument('--nothd',
                      action='store_false',
                      help='Use this flag to isable checking if the first audio track is DTSHD-MA, converting it to TrueHD 5.1, and seting it as the first audio track. It does that by default, this flag turnss that off.')
  parser.add_argument('-k',
                      '--keep',
                      type=comma_separated_ints,
                      default=[],
                      help='Stream indexes to force-keep as a final override after all automatic filtering, comma-separated. eg: -k 3,4')
  parser.add_argument('-r',
                      '--remove',
                      type=comma_separated_ints,
                      default=[],
                      help='Stream indexes to force-remove as a final override after all automatic filtering, comma-separated. eg: -r 3,4')
  parser.add_argument('--minsave',
                      type=parse_size,
                      default='100m',
                      help='Ignore files where the total space saving is less than this value. Supports suffixes: b, k, m, g. eg: 500m, 1g. Default: 100m')
  args = parser.parse_args()
  FILEPATHS = args.filepaths
  if args.languages is None:
    LANGUAGES = ['eng']
    LANGUAGES_EXPLICIT = False
  else:
    LANGUAGES = args.languages
    LANGUAGES_EXPLICIT = True
  EXECUTE   = args.run
  DEBUG     = args.debug
  NODEL     = args.nodel
  THD       = args.nothd
  KEEP_INDEXES = args.keep
  REMOVE_INDEXES = args.remove

  if not EXECUTE:
    print("\nDRYRUN - NO CHANGES WILL BE MADE. ADD '--run' TO MAKE CHANGES\n")
    if LANGUAGES_EXPLICIT:
      print(f"Would keep only [{', '.join(LANGUAGES)}] for both audio and subtitles (no auto-detection)")
    else:
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
  MIN_SAVE_BYTES = args.minsave
  for infile in files:
    if DEBUG: print("infile : ", infile)
    cmd, saveable_bytes, kept_bytes, file_summary, langs_kept, is_dtshd_ma, thd_added_bytes = gen_cmd(infile)
    if cmd is not None:
      total_bytes = saveable_bytes + kept_bytes
      net_saved_bytes = saveable_bytes - thd_added_bytes
      saveable_space = format_bytes(saveable_bytes)
      total_file_size = format_bytes(total_bytes)
      percent_saved = int((saveable_bytes / total_bytes) * 100) if total_bytes else 0

      if saveable_bytes < MIN_SAVE_BYTES and not is_dtshd_ma:
        if DEBUG: print(f"Saveable space {saveable_space} is less than {format_bytes(MIN_SAVE_BYTES)} and no THD conversion needed. Skipping {infile.split('/')[-1]}")
        continue

      breakdown.append([infile, saveable_space, saveable_bytes, percent_saved, total_file_size, is_dtshd_ma, thd_added_bytes])
      total_bytes_saved += net_saved_bytes
      print("\n--------------------------------------------------------------------------------")
      print(f"Keeping languages: {', '.join(langs_kept)}")
      for fs in file_summary:
        print(fs)
      out_line = f"Space to save: {saveable_space}.  ({percent_saved}% of {total_file_size})"
      if thd_added_bytes > 0:
        out_line += f"  New THD track: +{format_bytes(thd_added_bytes)}"
        out_line += f"  Net: {format_bytes(abs(net_saved_bytes))}" + (" saved" if net_saved_bytes >= 0 else " added")
      print(out_line)
      print("-" * len(out_line))
      print(cmd, "\n")
      if EXECUTE:
        subprocess.run(cmd, shell=True)
        print("Done\n")

  if not breakdown:
    print("No files needed thinning")
  else:
    breakdown = sorted(breakdown, key=lambda item: item[2] - item[6])
    for b in breakdown:
      net = b[2] - b[6]
      net_str = format_bytes(abs(net)) + (" saved" if net >= 0 else " added")
      percent = f"({b[3]}% of {b[4]})"
      thd_tag = "" if not THD else "New THD -> " if b[5] else "           "
      print(f"{thd_tag}{net_str.ljust(18)} {percent.ljust(17)} : {b[0].split('/')[-1]}")
    if total_bytes_saved != 0:
      net_label = "Saved" if total_bytes_saved >= 0 else "Added"
      if EXECUTE:
        print(f"\nTotal Space {net_label} : {format_bytes(abs(total_bytes_saved))}")
      else:
        print(f"\nTotal net space change : {format_bytes(abs(total_bytes_saved))} {net_label.lower()}")
