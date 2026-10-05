export interface MatchDeduction {
  skill?: string;
  reason: string;
  points: number;
}

export interface ScoreBreakdown {
  verdict?: string;
  strengths?: string[];
  gaps?: string[];
  capability_fit?: number;
  tooling_fit?: number;
  seniority_fit?: number;
  tech_stack_fit?: number;
  domain_fit?: number;
  capability_explanation?: string;
  tooling_explanation?: string;
  seniority_explanation?: string;
  math_score?: number;
  llm_score?: number;
  inferred_skills?: string[];
  deductions?: MatchDeduction[];
  weights?: {
    math: number;
    llm: number;
  };
}

export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  region: "india" | "us" | "remote";
  matchScore: number; // 0 to 100
  matchedSkills: string[];
  inferredSkills?: string[];
  missingSkills?: string[];
  explanation?: string;
  scoreBreakdown?: ScoreBreakdown;
  description: string;
  url: string;
  postedAt?: string;
  ats?: string;
}
