"""
String and character tools.
"""

punctuation = set(';:.,!?')

def classify(string):
	"Identify the class of the given character."
	if string.isalpha():
		return 'alpha'
	if string in punctuation:
		return 'punctuation'
	if string.isdecimal():
		return 'decimal'
