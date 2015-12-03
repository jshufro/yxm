#!/usr/bin/env python
import argparse
import redis
import urllib2
import urllib
import json as JSON
import requests
import requests.auth
import calendar
import time

parser = argparse.ArgumentParser(prog="yxm", description= \
	"""YouTube Ex Machina:
	   A bot to post new videos from a youtube channel
	   to a subreddit or subreddits.""")

parser.add_argument('-d', '--db', help='Address of the redis db to use (ie: \'redis://127.0.0.1:6379/0\'', default='redis://127.0.0.1:6379/0')
channel_group = parser.add_mutually_exclusive_group(required=True)
channel_group.add_argument('-c', '--channel', help='Name of the channel (ie: XXX where url is youtube.com/user/XXX)')
channel_group.add_argument('-o', '--channel-id', help='ID of the channel (ie: XXX where url is youtube.com/channel/XXX)')
parser.add_argument('-r', '--reddits', help='List of subreddits to post to (ie: \'yxm yxmtest\' where url is \'/r/yxm\' and \'/r/yxmtest\')', nargs='+', required=True)
parser.add_argument('-b', '--blacklist', help='List of videos to exclude (ie: RoltZ7XjaAk where url is v=RoltZ7XjaAk)', nargs='*')
parser.add_argument('-i', '--reddit-client-id', help='Reddit OAUTH client id', required=True)
parser.add_argument('-s', '--reddit-client-secret', help='Reddit OAUTH client secret', required=True)
parser.add_argument('-u', '--reddit-user', help='Reddit username', required=True)
parser.add_argument('-p', '--reddit-password', help='Reddit password', required=True)
parser.add_argument('-y', '--youtube-api-key', help='YouTube API key', required=True)
parser.add_argument('-f', '--logfile', help='A log file to write to', type=argparse.FileType('a'))

args = parser.parse_args()

#detect logfile
debug = not args.logfile == None
def log(s):
	if debug:
		args.logfile.write(str(s))	
		args.logfile.write('\n')

#Connect to redis
r = redis.from_url(args.db);

#log the time
log("\nUnix timestamp %d" % calendar.timegm(time.gmtime()))

#blacklist from arguments
if args.blacklist != None:
	for vid in args.blacklist:
		r.sadd(args.channel, vid)

	log("Blacklisted: %s" % str(args.blacklist))

#Query channel for id of uploads playlist
if args.channel != None:
	url = ("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&forUsername=%s&key=%s" % (args.channel, args.youtube_api_key))
else:
	url = ("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id=%s&key=%s" % (args.channel_id, args.youtube_api_key))
log(url)

response = urllib2.urlopen(url)
json = JSON.loads(response.read())
playlist_id = json.get("items")[0].get("contentDetails").get("relatedPlaylists").get("uploads")
log("Using playlist ID: %s" % playlist_id)

#Query channel for uploads playlist
url = ("https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId=%s&key=%s" % (playlist_id, args.youtube_api_key))

videos = []

while(True):
	log(url)
	response = urllib2.urlopen(url)
	json = JSON.loads(response.read())

	next_page_token = json.get("nextPageToken")

	for item in json.get("items"):
		snip = item.get("snippet")
		videos.append((snip.get("resourceId").get("videoId"), snip.get("title")))

	if next_page_token == None:
		break

	url = ("https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId=%s&key=%s&pageToken=%s" % (playlist_id, args.youtube_api_key, next_page_token))

log("Found %d videos" % len(videos))

#Filter videos already in redis
unposted = filter(lambda v: False if r.sismember(args.channel, v[0]) else True, videos)

log("Found %d videos to post" % len(unposted))
if (len(unposted) == 0):
	exit()

#Connect to reddit and auth
client_auth = requests.auth.HTTPBasicAuth(args.reddit_client_id, args.reddit_client_secret)
post_data = {"grant_type" : "password", "username":args.reddit_user, "password": args.reddit_password}
headers = {"User-Agent" : "YouTubeExMachina (YXM) for Reddit v0.1 by /u/jshufro"}
response = requests.post("https://www.reddit.com/api/v1/access_token", auth=client_auth, data=post_data, headers=headers)

access_token = response.json().get("access_token")
log("Using access token: %s" % access_token)

headers.update({"Authorization" : "bearer %s" % access_token})

#Do we need to do a CAPTCHA? Oh, the irony
response = requests.get("https://oauth.reddit.com/api/needs_captcha", headers=headers)
if response.text.lower() == "true":
	log("Please ensure your bot's account has at least 2 link karma so it doesn't need to do captchas")
	exit()

count = 0
rcount = len(args.reddits)
for v in unposted:
	for reddit in args.reddits:
		attempt = 0
		success = False
		while attempt <= 4 and success == False:
			attempt = attempt + 1
			try:
				post_data = {"sr" : reddit, "title" : v[1], "url" : "http://www.youtube.com/watch?v=%s" % v[0], "kind" : "link", "api_type":"json"}
				url = "https://oauth.reddit.com/api/submit"

				response = requests.post(url, headers=headers, data=post_data)

				json = response.json()
				if not json.get("error") == None:
					log("Received an error code from Reddit while posting %s to /r/%s: %s" % (v[1], reddit, json.get("error")))
					continue
				
				log("Posted %s to /r/%s" % (v[1], reddit))
				r.sadd(args.channel, v[0])
				success = True
				count = count + 1
			except requests.exceptions.ConnectionError:
				log("Connection error, retrying at most 3 times")
r.bgsave()
del r
log("All done. Posted %d videos across %d subs" % (count, rcount))
