/**
 * The Connections settings section, rendered as one accordion card per service.
 *
 * A secret equal to the server mask ('********') has not been replaced by the user: it
 * counts as configured, but the probe omits it so the backend tests its stored value.
 */

import React from 'react';
import type { ConfigValue, SettingsDraft, SettingsSection as SectionModel } from '../fieldModel/types';
import { ConnectionCard } from '../ConnectionCard/ConnectionCard';
import type { StatusTone } from '../ConnectionCard/ConnectionCard';
import { FieldRow } from '../SettingsSection/SettingsSection';
import { SettingsBlock } from '../../../components/primitives/SettingsBlock/SettingsBlock';
import { errorDetail } from '../../../api/client';
import { useTestConnection } from '../../../api/hooks/settings';
import { SECRET_MASK } from '../../../api/types/settings';

export interface ConnectionsPanelProps {
  section: SectionModel;
  values: SettingsDraft;
  /** Same contract as SettingsSection. */
  onChange: (key: string, value: ConfigValue | null) => void;
  /** Keys that require a full re-index on change. */
  reindexKeys: ReadonlySet<string>;
  /** Keys currently on their coded default. */
  defaultKeys: ReadonlySet<string>;
}

type ServiceName = 'paperless' | 'openai' | 'ollama';

interface ServiceStatus {
  tone: StatusTone;
  label: string;
}

/** Static presentation for each connection card, in display order. */
interface CardDef {
  service: ServiceName;
  /** Field-model group id holding this service's fields. */
  groupId: string;
  glyph: string;
  title: string;
}

const CARD_DEFS: readonly CardDef[] = [
  { service: 'paperless', groupId: 'paperless', glyph: 'P', title: 'Paperless-ngx' },
  { service: 'openai', groupId: 'openai', glyph: 'AI', title: 'OpenAI' },
  { service: 'ollama', groupId: 'ollama', glyph: 'Ll', title: 'Ollama' },
];

function isMasked(v: string): boolean {
  return v === SECRET_MASK;
}

function isConfigured(service: ServiceName, values: SettingsDraft): boolean {
  switch (service) {
    case 'paperless': {
      const url = values['PAPERLESS_URL'];
      return typeof url === 'string' && url.trim().length > 0;
    }
    case 'openai': {
      const key = values['OPENAI_API_KEY'];
      // Masked value (still the server mask) counts as configured.
      return typeof key === 'string' && key.trim().length > 0;
    }
    case 'ollama': {
      const url = values['OLLAMA_BASE_URL'];
      return typeof url === 'string' && url.trim().length > 0;
    }
  }
}

/**
 * Auto-tests each configured service on mount, staggered by 200ms; unconfigured
 * services show "Not configured" without probing.
 */
export function ConnectionsPanel({
  section,
  values,
  onChange,
  reindexKeys,
  defaultKeys,
}: ConnectionsPanelProps): React.ReactElement {
  const testMutation = useTestConnection();

  const [statuses, setStatuses] = React.useState<Record<ServiceName, ServiceStatus>>({
    paperless: { tone: 'untested', label: 'Untested' },
    openai: { tone: 'untested', label: 'Untested' },
    ollama: { tone: 'untested', label: 'Untested' },
  });

  const setStatus = (service: ServiceName, status: ServiceStatus): void => {
    setStatuses((prev) => ({ ...prev, [service]: status }));
  };

  const buildProbeBody = (service: ServiceName) => {
    const paperlessUrl = typeof values['PAPERLESS_URL'] === 'string' ? values['PAPERLESS_URL'] : '';
    const paperlessToken = typeof values['PAPERLESS_TOKEN'] === 'string' ? values['PAPERLESS_TOKEN'] : '';
    const openaiKey = typeof values['OPENAI_API_KEY'] === 'string' ? values['OPENAI_API_KEY'] : '';
    const ollamaUrl = typeof values['OLLAMA_BASE_URL'] === 'string' ? values['OLLAMA_BASE_URL'] : '';

    switch (service) {
      case 'paperless':
        return {
          service: 'paperless' as const,
          // The base fields are always sent for backwards compatibility.
          paperless_url: paperlessUrl,
          // Masked token: send empty so the server uses its stored secret.
          paperless_token: isMasked(paperlessToken) ? '' : paperlessToken,
        };
      case 'openai':
        return {
          service: 'openai' as const,
          paperless_url: '',
          paperless_token: '',
          ...(!isMasked(openaiKey) && openaiKey.length > 0 ? { openai_api_key: openaiKey } : {}),
        };
      case 'ollama':
        return {
          service: 'ollama' as const,
          paperless_url: '',
          paperless_token: '',
          ollama_base_url: ollamaUrl,
        };
    }
  };

  const probeService = React.useCallback(async (service: ServiceName): Promise<void> => {
    if (!isConfigured(service, values)) {
      setStatus(service, { tone: 'off', label: 'Not configured' });
      return;
    }
    setStatus(service, { tone: 'untested', label: 'Testing…' });
    try {
      const body = buildProbeBody(service);
      const result = await testMutation.mutateAsync(body);
      if (result.ok) {
        const count = result.document_count;
        const label =
          service === 'paperless' && count != null
            ? `${count.toLocaleString()} docs`
            : 'Connected';
        setStatus(service, { tone: 'ok', label });
      } else {
        setStatus(service, { tone: 'err', label: result.detail ?? 'Error' });
      }
    } catch (e) {
      setStatus(service, { tone: 'err', label: errorDetail(e, 'Error') });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);

  React.useEffect(() => {
    const services: ServiceName[] = ['paperless', 'openai', 'ollama'];
    const timers: ReturnType<typeof setTimeout>[] = [];

    services.forEach((service, index) => {
      if (!isConfigured(service, values)) {
        setStatus(service, { tone: 'off', label: 'Not configured' });
        return;
      }
      const timer = setTimeout(() => {
        void probeService(service);
      }, index * 200);
      timers.push(timer);
    });

    return () => {
      for (const timer of timers) clearTimeout(timer);
    };
  // Mount only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const groupById = React.useMemo(() => {
    const map: Record<string, typeof section.groups[0]> = {};
    for (const group of section.groups) {
      map[group.id] = group;
    }
    return map;
  }, [section]);

  return (
    <SettingsBlock
      id={section.id}
      title={section.title}
      subtitle={section.subtitle}
    >
      {CARD_DEFS.map((def) => {
        const group = groupById[def.groupId];
        if (group === undefined) return null;
        return (
          <ConnectionCard
            key={def.service}
            glyph={def.glyph}
            title={def.title}
            {...(group.subtitle !== undefined ? { subtitle: group.subtitle } : {})}
            status={statuses[def.service]}
            onTest={() => { void probeService(def.service); }}
          >
            {group.fields.map((field, index) => (
              <FieldRow
                key={field.key}
                field={field}
                values={values}
                reindexKeys={reindexKeys}
                defaultKeys={defaultKeys}
                onChange={onChange}
                last={index === group.fields.length - 1}
              />
            ))}
          </ConnectionCard>
        );
      })}
    </SettingsBlock>
  );
}
