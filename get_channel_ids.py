from dotenv import load_dotenv
load_dotenv()
import os
from googleapiclient.discovery import build

yt = build('youtube', 'v3', developerKey=os.environ['YOUTUBE_API_KEY'])

handles = ['RevengeKarmaTales', 'KarmaRevengeStories1', 'RevengeGlow', 'KarmaStoriesbyRevenge']

for handle in handles:
    resp = yt.channels().list(part='id,snippet', forHandle=handle).execute()
    if resp.get('items'):
        item = resp['items'][0]
        channel_id = item['id']
        title = item['snippet']['title']
        print(f'{handle}: {channel_id} - {title}')
    else:
        print(f'{handle}: NOT FOUND')
