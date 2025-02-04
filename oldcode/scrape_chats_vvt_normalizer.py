import os
import re
import gzip
import json
import sys
import argparse
import subprocess
from datetime import datetime, timedelta

# todo
# options:
# -a --audio audio
# -t --transcribe force transcription


# mutex required:
# --channel download whole channel
# --video download video



# todo
# if video given, collect channel name
# confirm transcript and chat same format
# modify the command line options to use above
# remove srt/vtt processing (only use for transcribe?)
# intelligently stop the download of videos in the yt-dlp subprocess call if we've already seen them (it takes a while to download the whole channel)

# checklist
# transcripts are downloaded
# chats are downloaded


"""
Function main():
    Input CHANNEL_URL
    video_list = get_video_list(CHANNEL_URL)
    For each VIDEO_URL in video_list:
        video_metadata = get_video_metadata(VIDEO_URL)
        start_time = get_video_start_time(video_metadata)
        download_subtitles(VIDEO_URL)
        adjust_subtitle_timestamps(VIDEO_URL, start_time)

Function get_video_list(CHANNEL_URL):
    Run command: yt-dlp --flat-playlist --dump-json CHANNEL_URL
    Collect the output (list of JSON lines)
    Initialize empty list video_list
    For each line in output:
        Parse JSON line to get 'url'
        Build full VIDEO_URL using 'url'
        Add VIDEO_URL to video_list
    Return video_list

Function get_video_metadata(VIDEO_URL):
    Run command: yt-dlp --dump-json VIDEO_URL
    Parse the JSON output to get video metadata
    Return video_metadata

Function get_video_start_time(video_metadata):
    If 'release_timestamp' in video_metadata:
        start_time = video_metadata['release_timestamp']
    Else if 'live_start_time' in video_metadata:
        start_time = video_metadata['live_start_time']
    Else if 'timestamp' in video_metadata:
        start_time = video_metadata['timestamp']
    Else:
        Print warning: "Cannot determine start time for VIDEO_URL"
        start_time = 0
    Return start_time

Function download_subtitles(VIDEO_URL):
    Run command: yt-dlp --write-auto-sub --sub-lang live_chat,en --skip-download VIDEO_URL
    This will download the live chat and the transcript subtitles

Function adjust_subtitle_timestamps(VIDEO_URL, start_time):
    Locate the subtitle files downloaded for VIDEO_URL (e.g., *.vtt files)
    For each subtitle file:
        Read the subtitle file content
        For each timestamp in the subtitle file:
            Convert timestamp to total seconds
            new_timestamp = start_time + timestamp_in_seconds
            Convert new_timestamp back to timestamp format
            Replace the timestamp in the subtitle file with new_timestamp
        Save the adjusted subtitle file

End of pseudocode
"""


def create_directories(channel):
    dirs = [
        channel,
        os.path.join(channel, 'downloaded'),
        os.path.join(channel, 'processed'),
        os.path.join(channel, 'transcripts_raw'),
        os.path.join(channel, 'transcripts'),
        os.path.join(channel, 'chats_raw'),
        os.path.join(channel, 'chats')
    ]
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d)

def get_channel_videos(channel):
    if channel.startswith('@'):
        channel_url = f"https://www.youtube.com/{channel}"
    elif channel.startswith('UC'):
        channel_url = f"https://www.youtube.com/channel/{channel}"
    else:
        channel_url = channel  # Assume it's a full URL

    cmd = ["yt-dlp", "--get-id", "--skip-download", channel_url]
    try:
        output = subprocess.check_output(cmd, text=True)
        video_ids = [line.strip() for line in output.strip().split('\n') if line.strip()]
    except subprocess.CalledProcessError as e:
        print(f"Error getting video list for channel {channel}: {e}")
        video_ids = []

    return video_ids

def is_chat_downloaded(channel, video_id):
    chat_file = os.path.join(channel, 'chats', f"{video_id}.txt")
    return os.path.exists(chat_file)

def is_transcript_downloaded(channel, video_id):
    transcript_file = os.path.join(channel, 'transcripts', f"{video_id}.txt")
    return os.path.exists(transcript_file)

def download_chat(channel, video_id):
    print(f"Downloading chat for video {video_id}")
    chat_output_path = os.path.join(channel, 'chats_raw')
    cmd = [
        "yt-dlp",
        "--write-subs",
        "--sub-lang", "live_chat",
        "--skip-download",
        "-o", os.path.join(chat_output_path, f"{video_id}.%(ext)s"),
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error downloading chat for video {video_id}: {e}")

def download_transcript(channel, video_id):
    print(f"Attempting to download transcript for video {video_id}")
    transcript_output_path = os.path.join(channel, 'transcripts_raw')
    cmd = [
        "yt-dlp",
        "--write-auto-sub",
        "--sub-lang", "en",
        "--skip-download",
        "-o", os.path.join(transcript_output_path, f"{video_id}.%(ext)s"),
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Transcript not available for video {video_id}: {e}")
        return False

def generate_transcript_with_whisper(channel, video_id):
    print(f"Generating transcript with Whisper for video {video_id}")
    audio_output_path = os.path.join(channel, 'downloaded')
    cmd_download_audio = [
        "yt-dlp",
        "-f", "bestaudio",
        "-o", os.path.join(audio_output_path, f"{video_id}.%(ext)s"),
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    try:
        subprocess.run(cmd_download_audio, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error downloading audio for video {video_id}: {e}")
        return

    audio_file = os.path.join(audio_output_path, f"{video_id}.webm")
    transcript_output_path = os.path.join(channel, 'transcripts_raw')
    cmd_whisper = [
        "whisper", audio_file,
        "--device", "cuda",
        "--language", "English",
        "--output_dir", transcript_output_path
    ]
    try:
        subprocess.run(cmd_whisper, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error generating transcript with Whisper for video {video_id}: {e}")

def get_video_start_time(video_id):
    cmd = ["yt-dlp", "-j", f"https://www.youtube.com/watch?v={video_id}"]
    try:
        output = subprocess.check_output(cmd, text=True)
        metadata = json.loads(output)
        if 'release_timestamp' in metadata and metadata['release_timestamp']:
            timestamp = metadata['release_timestamp']
        elif 'timestamp' in metadata and metadata['timestamp']:
            timestamp = metadata['timestamp']
        elif 'upload_date' in metadata and metadata['upload_date']:
            date_str = metadata['upload_date']
            timestamp = datetime.strptime(date_str, '%Y%m%d').timestamp()
        else:
            print(f"Cannot determine start time for video {video_id}")
            return None
        start_time = datetime.fromtimestamp(timestamp)
        return start_time
    except subprocess.CalledProcessError as e:
        print(f"Error getting metadata for video {video_id}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing metadata for video {video_id}: {e}")
        return None

def process_chat_file(channel, video_id, start_time):
    if start_time is None:
        print(f"Cannot process chat for video {video_id} without start time")
        return

    chat_raw_file = os.path.join(channel, 'chats_raw', f"{video_id}.live_chat.json")
    if not os.path.exists(chat_raw_file):
        print(f"Raw chat file not found for video {video_id}")
        return

    output_file_path = os.path.join(channel, 'chats', f"{video_id}.txt")

    with open(chat_raw_file, 'r', encoding='utf-8') as input_file, open(output_file_path, 'w', encoding='utf-8') as output_file:
        for line in input_file:
            line = line.strip()
            try:
                json_data = json.loads(line)
            except json.JSONDecodeError:
                print(f"Invalid JSON: {line}")
                continue

            # Extract timestamp
            replay_action = json_data.get('replayChatItemAction')
            if not replay_action:
                continue

            video_offset_time_msec = replay_action.get('videoOffsetTimeMsec')
            if not video_offset_time_msec:
                continue

            try:
                timestamp_ms = int(video_offset_time_msec)
            except ValueError:
                print(f"Invalid videoOffsetTimeMsec value: {line}")
                continue

            # Convert timestamp to datetime
            message_time = start_time + timedelta(milliseconds=timestamp_ms)

            # Process each action
            actions = replay_action.get('actions', [])
            for action in actions:
                add_chat_item_action = action.get('addChatItemAction')
                if not add_chat_item_action:
                    continue

                item = add_chat_item_action.get('item', {})
                live_chat_renderer = item.get('liveChatTextMessageRenderer')
                if not live_chat_renderer:
                    continue

                # Extract user
                author_name = live_chat_renderer.get('authorName', {})
                user = author_name.get('simpleText', '')
                if not user:
                    user = live_chat_renderer.get('authorExternalChannelId', '')
                if not user:
                    continue

                # Extract message
                message = ''
                message_runs = live_chat_renderer.get('message', {}).get('runs', [])
                for run in message_runs:
                    text = run.get('text')
                    if text:
                        message += text
                    else:
                        emoji = run.get('emoji', {})
                        emoji_id = emoji.get('shortcuts', [''])[0]
                        message += emoji_id

                if not message:
                    continue

                message = message.replace("\n", " ").replace("\t", " ")

                output_file.write(f"{message_time}\t{user}\t{message}\n")

def parse_vtt_file(f_in, f_out, start_time):
    f_in.readline()
    for line in f_in:
        line = line.strip()
        if '-->' in line:
            times = line.split(' --> ')
            if len(times) != 2:
                continue
            start_ts = times[0]
            time_parts = start_ts.split(':')
            hours = int(time_parts[0])
            minutes = int(time_parts[1])
            seconds = float(time_parts[2].replace(',', '.'))
            total_seconds = hours * 3600 + minutes * 60 + seconds
            message_time = start_time + timedelta(seconds=total_seconds)
            text_lines = []
            while True:
                text_line = f_in.readline().strip()
                if text_line == '':
                    break
                text_lines.append(text_line)
            message = ' '.join(text_lines).replace('\n', ' ').replace('\t', ' ')
            f_out.write(f"{message_time}\t{message}\n")

def parse_srt_file(f_in, f_out, start_time):
    while True:
        index_line = f_in.readline()
        if not index_line:
            break
        index_line = index_line.strip()
        if not index_line.isdigit():
            continue
        timestamp_line = f_in.readline().strip()
        times = timestamp_line.split(' --> ')
        if len(times) != 2:
            continue
        start_ts = times[0]
        time_parts = start_ts.split(':')
        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        seconds = float(time_parts[2].replace(',', '.'))
        total_seconds = hours * 3600 + minutes * 60 + seconds
        message_time = start_time + timedelta(seconds=total_seconds)
        text_lines = []
        while True:
            text_line = f_in.readline()
            if not text_line or text_line.strip() == '':
                break
            text_lines.append(text_line.strip())
        message = ' '.join(text_lines).replace('\n', ' ').replace('\t', ' ')
        f_out.write(f"{message_time}\t{message}\n")

def process_transcript_file(channel, video_id, start_time):
    if start_time is None:
        print(f"Cannot process transcript for video {video_id} without start time")
        return

    transcript_raw_dir = os.path.join(channel, 'transcripts_raw')
    transcript_file = None
    for ext in ['.en.vtt', '.en.srt', '.vtt', '.srt', '.en.vtt']:
        candidate = os.path.join(transcript_raw_dir, f"{video_id}{ext}")
        if os.path.exists(candidate):
            transcript_file = candidate
            break

    if transcript_file is None:
        print(f"Transcript file not found for video {video_id}")
        return

    output_file_path = os.path.join(channel, 'transcripts', f"{video_id}.txt")

    with open(transcript_file, 'r', encoding='utf-8') as f_in, open(output_file_path, 'w', encoding='utf-8') as f_out:
        first_line = f_in.readline()
        f_in.seek(0)
        if 'WEBVTT' in first_line:
            parse_vtt_file(f_in, f_out, start_time)
        else:
            parse_srt_file(f_in, f_out, start_time)

def process_channel(channel, force_whisper=False):
    create_directories(channel)
    videos = get_channel_videos(channel)
    for video_id in videos:
        if not is_chat_downloaded(channel, video_id):
            download_chat(channel, video_id)

        if not is_transcript_downloaded(channel, video_id):
            transcript_downloaded = download_transcript(channel, video_id)
            if not transcript_downloaded and force_whisper:
                generate_transcript_with_whisper(channel, video_id)

        start_time = get_video_start_time(video_id)

        process_chat_file(channel, video_id, start_time)
        process_transcript_file(channel, video_id, start_time)

def main():
    parser = argparse.ArgumentParser(description="Download YouTube video transcripts and chats.")
    parser.add_argument('channels', nargs='+', help='List of YouTube channel URLs or IDs.')
    parser.add_argument('--force-whisper', action='store_true', help='Force using Whisper to generate transcripts.')
    args = parser.parse_args()

    for channel in args.channels:
        print(f"Processing channel: {channel}")
        process_channel(channel, force_whisper=args.force_whisper)

if __name__ == "__main__":
    main()
