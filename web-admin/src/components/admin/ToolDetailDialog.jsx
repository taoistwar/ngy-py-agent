import { useEffect, useRef, useState } from "react"
import { testTool } from "../../api"
import { normalizeParameters } from "./AgentDetail"
import Modal from "./Modal"
import ToolDetailBody from "./ToolDetailBody"
import { buildArguments, initialValues, localizedText } from "./toolMeta"

// Why an argument could not be turned into a value, keyed by buildArguments'
// error kind.
const ARGUMENT_ERROR_KEYS = {
  missing: "toolTestMissing",
  number: "toolTestInvalidNumber",
  json: "toolTestInvalidJson",
}

export default function ToolDetailDialog({
  tool,
  agents,
  locale,
  showEnglish,
  onToggleLanguage,
  onClose,
  translate,
}) {
  const params = normalizeParameters(tool.parameters)
  const translation = localizedText(tool, locale)
  const [values, setValues] = useState(() => initialValues(params))
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState(null)
  const [inputError, setInputError] = useState("")
  const resultRef = useRef(null)

  // The result box sits above the inputs; scroll it into view so pressing Test
  // looks like it did something.
  useEffect(() => {
    if (!result) return
    resultRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [result])

  // The backend route runs without the confirmation gate, so a gated tool has to
  // be confirmed here instead.
  const gated = Boolean(tool.permission) && tool.permission !== "none"

  const setValue = (name, value) =>
    setValues((previous) => ({ ...previous, [name]: value }))

  const runTest = async () => {
    setInputError("")
    const built = buildArguments(params, values)
    if (built.error) {
      setInputError(`${translate(ARGUMENT_ERROR_KEYS[built.error.kind])}: ${built.error.name}`)
      return
    }
    if (gated && !window.confirm(translate("toolTestGatedConfirm"))) {
      return
    }

    setTesting(true)
    setResult(null)
    try {
      setResult(await testTool(tool.name, built.arguments))
    } catch (error) {
      setResult({ ok: false, error: error?.message || translate("errorUnknown") })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Modal
      wide
      className="modal-dialog-tool"
      title={tool.name}
      hint={translate("toolDetailHint")}
      closeLabel={translate("dialogClose")}
      onClose={onClose}
    >
      <ToolDetailBody
        tool={tool}
        agents={agents}
        translate={translate}
        translation={translation}
        showEnglish={showEnglish}
        onToggleLanguage={onToggleLanguage}
        params={params}
        values={values}
        onChange={setValue}
        inputError={inputError}
        onRun={runTest}
        testing={testing}
        result={result}
        resultRef={resultRef}
      />
    </Modal>
  )
}
