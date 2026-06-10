/**
 * ConnectionsPanel — the Connections section rendered as integration accordion cards.
 *
 * Replaces the flat SettingsSection rendering for section.id === 'connections'.
 * Renders:
 *   1. An AI-provider strip (LLM_PROVIDER segmented control).
 *   2. A ConnectionCard for Paperless-ngx (always visible).
 *   3. A ConnectionCard for OpenAI (always visible).
 *   4. A ConnectionCard for Ollama (only when LLM_PROVIDER === 'ollama').
 *
 * On mount each visible service with credentials configured is auto-tested
 * (staggered by 200ms per index). Services with empty required credentials
 * show "Not configured" without probing. Each card's "Test" button re-runs
 * the probe for that one service.
 *
 * Masked-secret detection: a value containing '•' is still the server mask —
 * the user has not replaced the secret. These count as "configured" (the server
 * will use its stored value), but the probe is sent with an empty/absent field
 * for that secret so the backend falls back to the stored one.
 *
 * Tier: features/ — composes ConnectionCard, FieldControl, fieldModel types.
 * Does NOT import sections.ts — the section is passed in as a prop.
 */

import React from 'react';
import type { ConfigValue, SettingsDraft, SettingsSection as SectionModel } from '../fieldModel/types';
import { ConnectionCard } from '../ConnectionCard/ConnectionCard';
import type { StatusTone } from '../ConnectionCard/ConnectionCard';
import { FieldControl } from '../FieldControl/FieldControl';
import { Row } from '../../../components/primitives/Row/Row';
import { SettingsBlock } from '../../../components/primitives/SettingsBlock/SettingsBlock';
import { useTestConnection } from '../../../api/hooks/settings';
import styles from './ConnectionsPanel.module.css';

export interface ConnectionsPanelProps {
  /** The 'connections' section descriptor. */
  section: SectionModel;
  /** Current draft values from the parent screen. */
  values: SettingsDraft;
  /** Called when any field changes — same contract as SettingsSection. */
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

/** True when a string value is still the server-side mask (contains bullet char). */
function isMasked(v: string): boolean {
  return v.includes('•');
}

/** True when a service has its required credential configured (non-empty). */
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
 * ConnectionsPanel — accordion Connections section.
 *
 * Renders the provider segmented strip, then one ConnectionCard per visible
 * service. Auto-tests each configured service on mount (staggered). Unconfigured
 * services display "Not configured" without probing.
 */
export function ConnectionsPanel({
  section,
  values,
  onChange,
  reindexKeys,
  defaultKeys,
}: ConnectionsPanelProps): React.ReactElement {
  const testMutation = useTestConnection();

  const provider = typeof values['LLM_PROVIDER'] === 'string' ? values['LLM_PROVIDER'] : 'openai';
  const showOllama = provider === 'ollama';

  const [statuses, setStatuses] = React.useState<Record<ServiceName, ServiceStatus>>({
    paperless: { tone: 'untested', label: 'Untested' },
    openai: { tone: 'untested', label: 'Untested' },
    ollama: { tone: 'untested', label: 'Untested' },
  });

  const setStatus = (service: ServiceName, status: ServiceStatus): void => {
    setStatuses((prev) => ({ ...prev, [service]: status }));
  };

  /** Build the probe body for a service, applying masked-secret logic. */
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
          // Masked token → send empty so server uses stored secret.
          paperless_token: isMasked(paperlessToken) ? '' : paperlessToken,
        };
      case 'openai':
        return {
          service: 'openai' as const,
          paperless_url: '',
          paperless_token: '',
          // Only send the key if the user has explicitly replaced it.
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

  /** Run the probe for one service; update status from the result. */
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
    } catch {
      setStatus(service, { tone: 'err', label: 'Error' });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);

  // Auto-test on mount: stagger by 200ms per service index.
  React.useEffect(() => {
    const visible: ServiceName[] = ['paperless', 'openai', ...(showOllama ? (['ollama'] as ServiceName[]) : [])];
    const timers: ReturnType<typeof setTimeout>[] = [];

    visible.forEach((service, index) => {
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
  // Only run on mount — deps intentionally empty.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Find field model groups from the section — looked up by group id.
  const groupById = React.useMemo(() => {
    const map: Record<string, typeof section.groups[0]> = {};
    for (const group of section.groups) {
      map[group.id] = group;
    }
    return map;
  }, [section]);

  const providerGroup = groupById['provider'];
  const paperlessGroup = groupById['paperless'];
  const openaiGroup = groupById['openai'];
  const ollamaGroup = groupById['ollama'];

  return (
    <SettingsBlock
      id={section.id}
      title={section.title}
      subtitle={section.subtitle}
    >
      {/* AI provider strip */}
      {providerGroup !== undefined && (
        <div className={styles['provider-strip']}>
          {providerGroup.fields.map((field) => (
            <FieldControl
              key={field.key}
              field={field}
              value={values[field.key]}
              onChange={onChange}
            />
          ))}
        </div>
      )}

      {/* Paperless-ngx card — always shown */}
      {paperlessGroup !== undefined && (
        <ConnectionCard
          glyph="P"
          glyphTone="blue"
          title="Paperless-ngx"
          {...(paperlessGroup.subtitle !== undefined ? { subtitle: paperlessGroup.subtitle } : {})}
          status={statuses['paperless']}
          onTest={() => { void probeService('paperless'); }}
        >
          {paperlessGroup.fields.map((field, index) => (
            <Row
              key={field.key}
              label={field.label}
              hint={field.hint}
              env={field.key}
              last={index === paperlessGroup.fields.length - 1}
              isDefault={defaultKeys.has(field.key)}
              requiresReindex={reindexKeys.has(field.key)}
            >
              <FieldControl
                field={field}
                value={values[field.key]}
                onChange={onChange}
              />
            </Row>
          ))}
        </ConnectionCard>
      )}

      {/* OpenAI card — always shown */}
      {openaiGroup !== undefined && (
        <ConnectionCard
          glyph="AI"
          glyphTone="teal"
          title="OpenAI"
          {...(openaiGroup.subtitle !== undefined ? { subtitle: openaiGroup.subtitle } : {})}
          status={statuses['openai']}
          onTest={() => { void probeService('openai'); }}
        >
          {openaiGroup.fields.map((field, index) => (
            <Row
              key={field.key}
              label={field.label}
              hint={field.hint}
              env={field.key}
              last={index === openaiGroup.fields.length - 1}
              isDefault={defaultKeys.has(field.key)}
              requiresReindex={reindexKeys.has(field.key)}
            >
              <FieldControl
                field={field}
                value={values[field.key]}
                onChange={onChange}
              />
            </Row>
          ))}
        </ConnectionCard>
      )}

      {/* Ollama card — only when provider is ollama */}
      {showOllama && ollamaGroup !== undefined && (
        <ConnectionCard
          glyph="Ll"
          glyphTone="grey"
          title="Ollama"
          {...(ollamaGroup.subtitle !== undefined ? { subtitle: ollamaGroup.subtitle } : {})}
          status={statuses['ollama']}
          onTest={() => { void probeService('ollama'); }}
        >
          {ollamaGroup.fields.map((field, index) => (
            <Row
              key={field.key}
              label={field.label}
              hint={field.hint}
              env={field.key}
              last={index === ollamaGroup.fields.length - 1}
              isDefault={defaultKeys.has(field.key)}
              requiresReindex={reindexKeys.has(field.key)}
            >
              <FieldControl
                field={field}
                value={values[field.key]}
                onChange={onChange}
              />
            </Row>
          ))}
        </ConnectionCard>
      )}
    </SettingsBlock>
  );
}
