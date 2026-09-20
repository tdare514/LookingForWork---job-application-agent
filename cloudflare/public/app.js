const jobs = document.querySelector("#jobs");

fetch("/api/jobs?limit=20")
  .then((response) => {
    if (!response.ok) throw new Error("API request failed");
    return response.json();
  })
  .then(({ jobs: rows }) => {
    jobs.replaceChildren(
      ...rows.map((job) => {
        const item = document.createElement("li");
        item.textContent = `${job.title} — ${job.company} (${job.location})`;
        return item;
      }),
    );
  })
  .catch(() => {
    jobs.replaceChildren(document.createTextNode("No local database configured."));
  });
