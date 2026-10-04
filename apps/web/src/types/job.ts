export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  region: "india" | "us" | "remote";
  matchScore: number; // 0 to 100
  matchedSkills: string[];
  missingSkills?: string[];
  description: string;
  url: string;
  postedAt?: string;
  ats?: string;
}
