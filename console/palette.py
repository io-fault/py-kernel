"""
Theme data. Colors and text borders.
"""

range_colors = {
	'start-inclusive': 0x00CC00,
	'stop-inclusive': 0xFF8700, # orange (between yellow and red)

	'offset-active': 0xF0F000, # yellow, actual position
	'offset-inactive': 0,

	'start-exclusive': 0x005F00,
	'stop-exclusive': 0xFF0000,
}

colors = {
	'teal': 0x005f5f,
	'orange': 0xff8700,
	'purple': 0x875fff,
	'cream': 0xffd787,
	'brick': 0x5f0000,
}

theme = {
	'comment': colors['brick'],
	'quotation': colors['teal'],
}
