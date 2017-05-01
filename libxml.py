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
	namespace = namespaces['sectors']

	@classmethod
	def struct_protocol(Class, element):
		"""
		# Construct a protocol reference from the given sectors:protocol element.
		"""
		params = {
			'limits': {},
			'resources': None,
		}

		pid = element.attrib.get('identifier')
		rsrc_set = element.findall("sectors:resource", namespaces)
		if len(rsrc_set) > 0:
			params['resources'] = {
				rsrc.attrib['identifier']: rsrc.attrib['{'+core.namespaces['xlink']+'}href']
				for rsrc in rsrc_set
			}

		return params

	@classmethod
	def structure(Class, document):
		"""
		# Given an xml/io.sectors document, extract the structures necessary
		# for starting a &.libdaemon based sectord process.
		"""
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

		interfaces = {
			ifelement.attrib["identifier"]: (
				# transport spec
				ifelement.attrib.get('transport', 'octets'),
				set(
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
			)
			for ifelement in ifelements
		}

		protocols = {
			protocol.attrib["identifier"]: Class.struct_protocol(protocol)
			for protocol in pelements
		}

		struct = {
			'libraries': libs,
			'interfaces': interfaces,
			'systems': None,
			'protocols': protocols,
			'concurrency': None if dist is None else int(dist),
		}

		return struct

	@classmethod
	def serialize(Class, xml, struct, chain=itertools.chain.from_iterable):
		"""
		# Serialize the given &struct using the &xml context.
		# The serialized form is not gauranteed to match the original
		# formatting of a document processed with &structure.
		# Generally, using serialize means that an interface is managing
		# the document.

		# [ Parameters ]
		# /(&..xml.library.Serialization)`xml`
			# The serializaiton context to use.
		# /struct
			# The, structured, data to serialize.
		"""
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
					('transport', transport_type),
				)
				for slot, (transport_type, spaces) in ifs.items()),
			)),
			('concurrency', struct.get('concurrency')),
			namespace = namespace,
		)
