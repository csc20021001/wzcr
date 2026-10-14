export type CourseSeed = {
  id: string;
  universityId: string;
  term: string;
  firstTerm: string;
  lastTerm: string;
  offeredTerms: string[];
  courseCode: string;
  name: string;
  department: string;
  officialSourceUrl: string;
  departmentSourceUrl: string;
  instructors: Array<{ name: string; officialSourceUrl?: string }>;
};

// The local importer writes a large generated TypeScript audit artifact using
// this type. Production receives the same data through split D1 migrations, so
// the audit artifact is intentionally excluded from the Worker bundle and Git.
