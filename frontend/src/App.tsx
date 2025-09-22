import { useEffect, useMemo, useState } from 'react'
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
} from '@assistant-ui/react'
import type {
  ChatModelAdapter,
  ChatModelRunResult,
} from '@assistant-ui/react'
import Editor from '@monaco-editor/react'
import './App.css'

type FileResponse = {
  path: string
  content: string
}

type ChatResponse = {
  reply: string
  editor_path?: string | null
  editor_content?: string | null
  usage?: Record<string, number>
}

const inferLanguage = (path: string | null): string => {
  if (!path) return 'plaintext'
  const lower = path.toLowerCase()
  if (lower.endsWith('.ts') || lower.endsWith('.tsx')) return 'typescript'
  if (lower.endsWith('.js') || lower.endsWith('.jsx')) return 'javascript'
  if (lower.endsWith('.py')) return 'python'
  if (lower.endsWith('.json')) return 'json'
  if (lower.endsWith('.md')) return 'markdown'
  if (lower.endsWith('.css')) return 'css'
  if (lower.endsWith('.html')) return 'html'
  if (lower.endsWith('.rs')) return 'rust'
  if (lower.endsWith('.go')) return 'go'
  return 'plaintext'
}

const MessageBubble = () => (
  <MessagePrimitive.Root className="message-row">
    <MessagePrimitive.If user>
      <div className="message-bubble message-bubble--user">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.If>
    <MessagePrimitive.If assistant>
      <div className="message-bubble message-bubble--assistant">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.If>
  </MessagePrimitive.Root>
)

const Composer = () => (
  <ComposerPrimitive.Root className="composer">
    <ComposerPrimitive.Input
      className="composer-input"
      placeholder="Ask the agent to read or edit a file"
    />
    <ComposerPrimitive.Send className="composer-send">
      Send
    </ComposerPrimitive.Send>
  </ComposerPrimitive.Root>
)

const apiBase = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'
const DEFAULT_FILE_PATH = 'files/example.py'

function App() {
  const [conversationId] = useState(() => crypto.randomUUID())
  const [editorPath, setEditorPath] = useState<string>(DEFAULT_FILE_PATH)
  const [editorContent, setEditorContent] = useState<string>(
    '# Loading example.py...\n'
  )

  useEffect(() => {
    let cancelled = false

    const loadDefault = async () => {
      try {
        const response = await fetch(`${apiBase}/api/file?path=${encodeURIComponent(DEFAULT_FILE_PATH)}`)
        if (!response.ok) {
          return
        }

        const data = (await response.json()) as FileResponse
        if (!cancelled) {
          setEditorPath(data.path)
          setEditorContent(data.content)
        }
      } catch {
        /* ignore bootstrap errors */
      }
    }

    loadDefault()

    return () => {
      cancelled = true
    }
  }, [apiBase])


  const chatAdapter = useMemo<ChatModelAdapter>(() => {
    const adapter: ChatModelAdapter = {
      async run({ messages, abortSignal }): Promise<ChatModelRunResult> {
        const latestUser = [...messages].reverse().find((m) => m.role === 'user')
        const text = latestUser?.content
          ?.filter((part) => part.type === 'text')
          .map((part) => part.text)
          .join('\n')
          .trim()

        if (!text) {
          return {
            content: [
              {
                type: 'text',
                text: 'Please enter a message for the agent.',
              },
            ],
            status: { type: 'incomplete', reason: 'other', error: 'empty-input' },
          }
        }

        try {
          const response = await fetch(`${apiBase}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              conversation_id: conversationId,
              message: text,
            }),
            signal: abortSignal,
          })

          if (!response.ok) {
            const errorText = await response.text()
            throw new Error(errorText || `HTTP ${response.status}`)
          }

          const data = (await response.json()) as ChatResponse

          if (abortSignal.aborted) {
            throw new DOMException('Run aborted', 'AbortError')
          }

          if (data.editor_content) {
            setEditorContent(data.editor_content)
          }
          if (data.editor_path) {
            setEditorPath(data.editor_path)
          }

          return {
            content: data.reply
              ? [
                  {
                    type: 'text' as const,
                    text: data.reply,
                  },
                ]
              : [],
            status: { type: 'complete', reason: 'stop' },
            metadata: {
              custom: {
                usage: data.usage,
                editorPath: data.editor_path,
              },
            },
          }
        } catch (error) {
          if (abortSignal.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
            throw error
          }

          const message =
            error instanceof Error ? error.message : 'Unexpected error contacting the backend.'

          return {
            content: [
              {
                type: 'text' as const,
                text: `Request failed: ${message}`,
              },
            ],
            status: { type: 'incomplete', reason: 'error', error: message },
          }
        }
      },
    }

    return adapter
  }, [conversationId])

  const runtime = useLocalRuntime(
    chatAdapter,
    useMemo(() => ({ initialMessages: [] as const }), [])
  )

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="layout">
        <section className="editor-pane">
          <div className="editor-content">
            <Editor
              height="100%"
              defaultLanguage="plaintext"
              language={inferLanguage(editorPath)}
              value={editorContent}
              theme="vs-dark"
              options={{
                readOnly: true,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                fontSize: 14,
              }}
            />
          </div>
        </section>
        <section className="chat-pane">
          <div className="chat-pane__inner">
            <ThreadPrimitive.Root className="thread-root">
              <ThreadPrimitive.Viewport className="thread-viewport">
                <ThreadPrimitive.Messages components={{ Message: MessageBubble }} />
              </ThreadPrimitive.Viewport>
              <ThreadPrimitive.ScrollToBottom className="scroll-button">
                Scroll to bottom
              </ThreadPrimitive.ScrollToBottom>
            </ThreadPrimitive.Root>
            <Composer />
          </div>
        </section>
      </div>
    </AssistantRuntimeProvider>
  )
}

export default App
