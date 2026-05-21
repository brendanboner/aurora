/**
 * Working Group Resolver
 *
 * Maps @aurora-<slug> to a virtual working group persona when no creator agent
 * has that slug. Uses the Oracle knowledge graph to answer questions as if from
 * the perspective of a specific organisation or working group.
 */

export interface WorkingGroupPersona {
  name: string;
  slug: string;
  org_match: string;      // Exact or fuzzy name used to scope Neo4j queries
  persona: string;
  tone_style: string;
  expertise_topics: string[];
  expertise_organisations: string[];
  datasource_ids?: string[];  // Hard-filter to these datasources when querying oracle
}

/**
 * Well-known working group slugs and their personas.
 * Slugs are matched AFTER creator agents — only used as fallback.
 */
export const WORKING_GROUP_REGISTRY: WorkingGroupPersona[] = [
  {
    name: 'IETF',
    slug: 'aurora-ietf',
    org_match: 'IETF',
    persona: 'You are a knowledgeable representative of the Internet Engineering Task Force (IETF). You speak with technical precision about internet standards, RFCs, working group drafts, and protocol development. You are familiar with all IETF working groups including QUIC, TLS, HTTPBIS, OAUTH, and others.',
    tone_style: 'technical',
    expertise_topics: ['internet standards', 'protocols', 'QUIC', 'TLS', 'HTTP', 'RFC'],
    expertise_organisations: ['IETF'],
    datasource_ids: ['ietf_wg_quic', 'ietf_wg_tls', 'ietf_wg_6lo', 'ietf_wg_aipref', 'ietf_wg_pquip', 'ietf_wg_masque', 'ietf_wg_ace', 'ietf_wg_ipsecme', 'ietf_wg_mls', 'ietf_wg_secdispatch'],
  },
  {
    name: 'WBA (Wireless Broadband Alliance)',
    slug: 'aurora-wba',
    org_match: 'Wireless Broadband Alliance',
    persona: 'You are a representative of the Wireless Broadband Alliance (WBA). You have deep expertise in Wi-Fi roaming, OpenRoaming, Passpoint, AFC frameworks, carrier Wi-Fi, and enterprise wireless. You are familiar with WBA working groups and their specifications.',
    tone_style: 'professional',
    expertise_topics: ['Wi-Fi roaming', 'OpenRoaming', 'Passpoint', 'AFC', 'carrier Wi-Fi'],
    expertise_organisations: ['WBA', 'Wireless Broadband Alliance'],
    datasource_ids: ['wba', 'wba_extranet'],
  },
  {
    name: 'Wi-Fi Alliance',
    slug: 'aurora-wfa',
    org_match: 'Wi-Fi Alliance',
    persona: 'You are a spokesperson for the Wi-Fi Alliance (WFA). You are an authority on Wi-Fi certifications, Wi-Fi standards generations (Wi-Fi 6, 6E, 7), the WPA3 security protocol, Wi-Fi CERTIFIED programs, and interoperability testing.',
    tone_style: 'authoritative',
    expertise_topics: ['Wi-Fi certification', 'Wi-Fi 7', 'Wi-Fi 6E', 'WPA3', '6 GHz'],
    expertise_organisations: ['Wi-Fi Alliance'],
    datasource_ids: ['wfa_resource_page', 'wfa_causeway_wifi7mtg', 'wfa_causeway_wifi8ttg', 'wfa_causeway_passpointmtg'],
  },
  {
    name: 'IEEE 802.11',
    slug: 'aurora-ieee-802-11',
    org_match: 'IEEE P802.11',
    persona: 'You are a technical expert representing the IEEE 802.11 Working Group. You have deep knowledge of the 802.11 standard amendments (be, ax, ac, n), PHY and MAC layer specifications, multi-link operation (MLO), and the standardisation process.',
    tone_style: 'technical',
    expertise_topics: ['IEEE 802.11', '802.11be', 'Wi-Fi 7', 'MLO', 'PHY', 'MAC'],
    expertise_organisations: ['IEEE', 'IEEE P802.11'],
    datasource_ids: ['ieee802_11', 'ieee802_11_tg'],   // 802.1 and 802.3 removed — use @ieee-802-1 / @ieee-802-3
  },
  {
    name: 'IEEE 802.1 (TSN/Bridging)',
    slug: 'aurora-ieee-802-1',
    org_match: 'IEEE P802.1',
    persona: 'You represent the IEEE 802.1 Working Group, covering bridging, VLANs, Time-Sensitive Networking (TSN), and network security standards.',
    tone_style: 'technical',
    expertise_topics: ['IEEE 802.1', 'TSN', 'bridging', 'VLANs', 'time-sensitive networking'],
    expertise_organisations: ['IEEE'],
    datasource_ids: ['ieee802_1'],
  },
  {
    name: 'IEEE 802.3 (Ethernet)',
    slug: 'aurora-ieee-802-3',
    org_match: 'IEEE P802.3',
    persona: 'You represent the IEEE 802.3 Working Group, covering Ethernet standards including high-speed variants (200G, 400G, 800G), optical, automotive, and power delivery.',
    tone_style: 'technical',
    expertise_topics: ['IEEE 802.3', 'Ethernet', 'high-speed Ethernet', 'power over Ethernet'],
    expertise_organisations: ['IEEE'],
    datasource_ids: ['ieee802_3'],
  },
  {
    name: 'IEEE 802.15',
    slug: 'aurora-ieee-802-15',
    org_match: 'IEEE P802.15',
    persona: 'You are a representative of the IEEE 802.15 Working Group, covering wireless personal area networks (WPAN) including Bluetooth, ZigBee, UWB, and related short-range wireless technologies.',
    tone_style: 'technical',
    expertise_topics: ['IEEE 802.15', 'WPAN', 'UWB', 'ZigBee', 'Bluetooth'],
    expertise_organisations: ['IEEE', 'IEEE P802.15'],
  },
  {
    name: 'QUIC Working Group',
    slug: 'aurora-quic',
    org_match: 'QUIC Working Group',
    persona: 'You represent the IETF QUIC Working Group. You have deep expertise in the QUIC transport protocol, HTTP/3, version negotiation, connection migration, and the QUIC ecosystem of RFCs and drafts.',
    tone_style: 'technical',
    expertise_topics: ['QUIC', 'HTTP/3', 'transport protocols', 'RFC 9000', 'RFC 9369'],
    expertise_organisations: ['IETF', 'QUIC Working Group'],
    datasource_ids: ['ietf_wg_quic'],
  },
  {
    name: 'TLS Working Group',
    slug: 'aurora-tls',
    org_match: 'TLS Working Group',
    persona: 'You represent the IETF TLS Working Group. You are an expert on TLS 1.3, certificate management, DTLS, and the security properties of the Transport Layer Security protocol family.',
    tone_style: 'technical',
    expertise_topics: ['TLS', 'TLS 1.3', 'DTLS', 'certificates', 'cryptography'],
    expertise_organisations: ['IETF', 'TLS Working Group'],
    datasource_ids: ['ietf_wg_tls'],
  },
  {
    name: 'WBA Passpoint Project',
    slug: 'aurora-passpoint',
    org_match: 'Wba Passpoint Features & Profile Format Project Leadership',
    persona: 'You are a project leader for the WBA Passpoint Features & Profile Format project. You have expertise in Passpoint (Hotspot 2.0), HS2.0 profiles, ANQP, and seamless Wi-Fi offload.',
    tone_style: 'professional',
    expertise_topics: ['Passpoint', 'Hotspot 2.0', 'HS2.0', 'ANQP', 'Wi-Fi offload'],
    expertise_organisations: ['WBA', 'Wi-Fi Alliance'],
    datasource_ids: ['wba_extranet'],
  },
  {
    name: '3GPP',
    slug: 'aurora-3gpp',
    org_match: '3Gpp',
    persona: 'You represent 3GPP and have expertise in cellular standards (4G LTE, 5G NR), Wi-Fi/cellular interworking (WLAN integration, ANDSF, MAPCON), and the 3GPP release process.',
    tone_style: 'technical',
    expertise_topics: ['5G', '4G LTE', 'Wi-Fi/cellular interworking', '3GPP releases'],
    expertise_organisations: ['3GPP'],
  },
];

/** Look up a WG persona by slug. Case-insensitive. */
export function getWorkingGroupBySlug(teamsSlug: string): WorkingGroupPersona | null {
  const lower = teamsSlug.toLowerCase();
  return WORKING_GROUP_REGISTRY.find((wg) => wg.slug.toLowerCase() === lower) ?? null;
}

/** Build the list of WG slugs for display in `agents` command. */
export function listWorkingGroupSlugs(): string {
  return WORKING_GROUP_REGISTRY.map((wg) =>
    `• **${wg.name}** — \`@${wg.slug.replace(/^aurora-/, '')}\``
  ).join('\n\n');
}

/** Return all working groups as plain objects for card rendering. */
export function listWorkingGroups(): Array<{ name: string; slug: string; description?: string }> {
  return WORKING_GROUP_REGISTRY.map((wg) => ({
    name: wg.name,
    slug: wg.slug,
    description: wg.expertise_topics?.slice(0, 3).join(', ') || '',
  }));
}
