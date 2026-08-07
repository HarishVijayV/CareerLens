export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-start justify-center gap-4 px-6">
      <h1 className="text-3xl font-semibold">CareerLens</h1>
      <p className="text-gray-600">
        A data-engineering pipeline, a multi-agent AI copilot, and a real product
        wrapped around one problem: understanding the job market and your fit in it.
        See <code>docs/PROJECT_STORY.md</code> in the repo for the full pitch.
      </p>
      <div className="flex gap-3">
        <a href="/signup" className="rounded bg-black px-4 py-2 text-white">
          Sign up
        </a>
        <a href="/login" className="rounded border px-4 py-2">
          Log in
        </a>
      </div>
    </main>
  );
}
