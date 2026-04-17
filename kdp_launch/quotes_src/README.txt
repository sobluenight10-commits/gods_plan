Drop numbered fragment files here (UTF-8), then run:
  python kdp_launch/merge_quotes_to_one_file.py

Expected filenames:
  001-180.txt   181-240.txt   241-360.txt   361-450.txt   451-540.txt
  541-630.txt   631-720.txt   721-810.txt   811-900.txt   901-990.txt   991-1080.txt

Line format (one quote per line):
  181 YOUR APHORISM IN FULL
  182. ANOTHER LINE

Lines starting with # are ignored.

Output files are written in kdp_launch/:
  home_to_myself_quotes_1_1080_MERGED.txt
  home_to_myself_quotes_MASTER.json
