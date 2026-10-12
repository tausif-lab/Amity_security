export default function SectionHeader({ title, children }) {
  return (
    <div className="text-center mb-8">
      <h1 className="text-3xl font-bold tracking-wide mb-2">{title}</h1>
      <p className="text-gray-400 text-xs leading-relaxed max-w-xl mx-auto">{children}</p>
    </div>
  );
}