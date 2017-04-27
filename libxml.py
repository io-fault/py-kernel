"""
# XML serialization and parsing for io related grammars.
"""
import collections
import itertools

from ..xml import library as core, libschema
from . import schemas

namespaces = libschema.index_namespace_labels(schemas)

class Sectors(libschema.Interface):
	"""
	# Interface configuration for sector daemons.
	"""
	#from .schemas import sectors as schema
	namespace = namespaces['sectors']

	@classmethod
	def structure(Class, document):
		find = lambda x: document.find(x, namespaces)
		findall = lambda x: document.findall(x, namespaces)
		get_local_name = (lambda x: x.tag[x.tag.rfind('}')+1:])

		libelements = findall("sectors:library")
		ifelements = findall("sectors:interface")
		pelements = findall("sectors:protocol")
		dist = document.attrib.get("concurrency", None)

		if libelements:
			libs = [
				(x.attrib["libname"], x.attrib["fullname"])
				for x in list(libelements)
			]
			libs = dict(libs)
		else:
			libs = None

		ifelements = list(ifelements)
		transport = str(ifelement.attrib.get("transport", "octets"))

		interfaces = {
			ifelement.attrib["identifier"]: set(
				itertools.chain.from_iterable([
					[
						(
							get_local_name(addrspace) + addrspace.attrib.get("version", ""),
							alloc.attrib["address"], alloc.attrib["port"]
						)
						for alloc in addrspace
					]
					for addrspace in ifelement
				])
			)
			for ifelement in ifelements
		}

		protocols = {
			ifelement.attrib["identifier"]: dict(
				itertools.chain.from_iterable([
					[
						(
						)
						for alloc in addrspace
					]
					for addrspace in ifelement
				])
			)
			for protocol in pelements
		}

		struct = {
			'libraries': libs,
			'interfaces': interfaces,
			'systems': None,
			'protocols': None,
			'concurrency': None if dist is None else int(dist),
		}

		return struct

	@classmethod
	def serialize(Class, xml, struct, chain=itertools.chain.from_iterable):
		ifs = {}

		for slot, allocs in struct.get('interfaces', ()).items():
			slot_allocs = ifs[slot] = collections.defaultdict(list)
			for alloc in allocs:
				slot_allocs[alloc.protocol].append((alloc.address, alloc.port))

		return xml.root('sectors', chain((
			xml.element('libraries', chain(
				xml.element('module', None, ('libname', x), ('fullname', fn))
				for x, fn in (struct.get('libraries', None) or {}).items()
			)), chain(
				xml.element('interface', chain(
					xml.element("local" if addrspace == "local" else addrspace[:-1], chain(
						xml.element('allocate', None,
							('address', address),
							('port', port)
						)
						for address, port in allocs),
						('version', None if addrspace == "local" else addrspace[-1:]),
					)
					for addrspace, allocs in spaces.items()),
					('identifier', slot),
				)
				for slot, spaces in ifs.items()),
			)),
			('concurrency', struct.get('concurrency')),
			namespace = namespace,
		)
