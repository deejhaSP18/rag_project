const SUGGESTIONS: [string, string][] = [
  ["Databases", "How many databases are there and which ones are SingleStore?"],
  ["Pipeline", "What is the purpose of each EDI DB?"],
  ["Celery", "How often do Celery tasks run?"],
  ["Claims", "How does the pipeline avoid duplicate claims?"],
];

export function Welcome({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="welcome">
      <h2>Ask your documents <em>anything.</em></h2>
      <p>Answers are written from your indexed files only — with the passages they came from, so you can check the work.</p>
      <div className="prompts">
        {SUGGESTIONS.map(([tag, question]) => (
          <button key={question} className="prompt" type="button" onClick={() => onPick(question)}>
            <small>{tag}</small>
            {question}
          </button>
        ))}
      </div>
    </div>
  );
}
