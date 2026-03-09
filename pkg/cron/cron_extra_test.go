package cron

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func setupCronService(t *testing.T) *CronService {
	t.Helper()
	storePath := filepath.Join(t.TempDir(), "cron", "jobs.json")
	return NewCronService(storePath, nil)
}

func TestNewCronService(t *testing.T) {
	cs := setupCronService(t)
	if cs == nil {
		t.Fatal("expected non-nil CronService")
	}
	if cs.store == nil {
		t.Fatal("expected non-nil store")
	}
}

func TestAddJob_Every(t *testing.T) {
	cs := setupCronService(t)

	job, err := cs.AddJob(
		"test job",
		CronSchedule{Kind: "every", EveryMS: int64Ptr(60000)},
		"hello",
		false,
		"cli",
		"direct",
	)
	if err != nil {
		t.Fatalf("AddJob failed: %v", err)
	}
	if job.ID == "" {
		t.Error("expected non-empty job ID")
	}
	if job.Name != "test job" {
		t.Errorf("expected name 'test job', got %q", job.Name)
	}
	if !job.Enabled {
		t.Error("expected job to be enabled")
	}
	if job.State.NextRunAtMS == nil {
		t.Error("expected next run time to be set")
	}
	if job.DeleteAfterRun {
		t.Error("expected DeleteAfterRun=false for every jobs")
	}
}

func TestAddJob_At(t *testing.T) {
	cs := setupCronService(t)

	futureMS := time.Now().Add(time.Hour).UnixMilli()
	job, err := cs.AddJob("one-time", CronSchedule{Kind: "at", AtMS: &futureMS}, "do this once", false, "", "")
	if err != nil {
		t.Fatalf("AddJob failed: %v", err)
	}
	if !job.DeleteAfterRun {
		t.Error("expected DeleteAfterRun=true for 'at' jobs")
	}
}

func TestAddJob_Cron(t *testing.T) {
	cs := setupCronService(t)

	job, err := cs.AddJob("cron job", CronSchedule{Kind: "cron", Expr: "0 * * * *"}, "hourly", false, "", "")
	if err != nil {
		t.Fatalf("AddJob failed: %v", err)
	}
	if job.State.NextRunAtMS == nil {
		t.Error("expected next run time for cron job")
	}
}

func TestListJobs_All(t *testing.T) {
	cs := setupCronService(t)
	_, _ = cs.AddJob("j1", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")
	_, _ = cs.AddJob("j2", CronSchedule{Kind: "every", EveryMS: int64Ptr(2000)}, "m", false, "", "")

	jobs := cs.ListJobs(true)
	if len(jobs) != 2 {
		t.Errorf("expected 2 jobs, got %d", len(jobs))
	}
}

func TestListJobs_EnabledOnly(t *testing.T) {
	cs := setupCronService(t)
	job1, _ := cs.AddJob("j1", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")
	_, _ = cs.AddJob("j2", CronSchedule{Kind: "every", EveryMS: int64Ptr(2000)}, "m", false, "", "")

	cs.EnableJob(job1.ID, false)

	jobs := cs.ListJobs(false)
	if len(jobs) != 1 {
		t.Errorf("expected 1 enabled job, got %d", len(jobs))
	}
}

func TestRemoveJob(t *testing.T) {
	cs := setupCronService(t)
	job, _ := cs.AddJob("removable", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")

	removed := cs.RemoveJob(job.ID)
	if !removed {
		t.Error("expected removal to succeed")
	}

	jobs := cs.ListJobs(true)
	if len(jobs) != 0 {
		t.Errorf("expected 0 jobs after removal, got %d", len(jobs))
	}
}

func TestRemoveJob_NotFound(t *testing.T) {
	cs := setupCronService(t)
	removed := cs.RemoveJob("nonexistent")
	if removed {
		t.Error("expected removal to fail for nonexistent job")
	}
}

func TestEnableJob(t *testing.T) {
	cs := setupCronService(t)
	job, _ := cs.AddJob("toggle", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")

	cs.EnableJob(job.ID, false)
	jobs := cs.ListJobs(false)
	if len(jobs) != 0 {
		t.Error("expected 0 enabled jobs after disabling")
	}

	cs.EnableJob(job.ID, true)
	jobs = cs.ListJobs(false)
	if len(jobs) != 1 {
		t.Error("expected 1 enabled job after re-enabling")
	}
}

func TestEnableJob_NotFound(t *testing.T) {
	cs := setupCronService(t)
	result := cs.EnableJob("nonexistent", true)
	if result != nil {
		t.Error("expected nil for nonexistent job")
	}
}

func TestUpdateJob(t *testing.T) {
	cs := setupCronService(t)
	job, _ := cs.AddJob("update-me", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "original", false, "", "")

	job.Payload.Message = "updated"
	err := cs.UpdateJob(job)
	if err != nil {
		t.Fatalf("UpdateJob failed: %v", err)
	}

	jobs := cs.ListJobs(true)
	if jobs[0].Payload.Message != "updated" {
		t.Errorf("expected 'updated', got %q", jobs[0].Payload.Message)
	}
}

func TestUpdateJob_NotFound(t *testing.T) {
	cs := setupCronService(t)
	err := cs.UpdateJob(&CronJob{ID: "nonexistent"})
	if err == nil {
		t.Error("expected error for nonexistent job")
	}
}

func TestStatus(t *testing.T) {
	cs := setupCronService(t)
	_, _ = cs.AddJob("j1", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")

	status := cs.Status()
	if status["jobs"] != 1 {
		t.Errorf("expected jobs=1, got %v", status["jobs"])
	}
	if status["enabled"] != false {
		t.Errorf("expected enabled=false before Start(), got %v", status["enabled"])
	}
}

func TestLoad(t *testing.T) {
	cs := setupCronService(t)
	_, _ = cs.AddJob("j1", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")

	// Create a new service pointing to same store
	cs2 := NewCronService(cs.storePath, nil)
	err := cs2.Load()
	if err != nil {
		t.Fatalf("Load failed: %v", err)
	}

	jobs := cs2.ListJobs(true)
	if len(jobs) != 1 {
		t.Errorf("expected 1 loaded job, got %d", len(jobs))
	}
}

func TestSetOnJob(t *testing.T) {
	cs := setupCronService(t)
	var called bool
	cs.SetOnJob(func(job *CronJob) (string, error) {
		called = true
		return "", nil
	})
	// Just verify no panic
	_ = called
}

func TestStartAndStop(t *testing.T) {
	cs := setupCronService(t)

	err := cs.Start()
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}
	if !cs.running {
		t.Error("expected running=true after Start()")
	}

	// Starting again should be idempotent
	err = cs.Start()
	if err != nil {
		t.Fatalf("double Start failed: %v", err)
	}

	cs.Stop()
	if cs.running {
		t.Error("expected running=false after Stop()")
	}

	// Stopping again should be idempotent
	cs.Stop()
}

func TestComputeNextRun_At_Future(t *testing.T) {
	cs := setupCronService(t)
	futureMS := time.Now().Add(time.Hour).UnixMilli()
	sched := &CronSchedule{Kind: "at", AtMS: &futureMS}
	next := cs.computeNextRun(sched, time.Now().UnixMilli())
	if next == nil || *next != futureMS {
		t.Errorf("expected future timestamp, got %v", next)
	}
}

func TestComputeNextRun_At_Past(t *testing.T) {
	cs := setupCronService(t)
	pastMS := time.Now().Add(-time.Hour).UnixMilli()
	sched := &CronSchedule{Kind: "at", AtMS: &pastMS}
	next := cs.computeNextRun(sched, time.Now().UnixMilli())
	if next != nil {
		t.Errorf("expected nil for past at-time, got %d", *next)
	}
}

func TestComputeNextRun_Every(t *testing.T) {
	cs := setupCronService(t)
	everyMS := int64(5000)
	sched := &CronSchedule{Kind: "every", EveryMS: &everyMS}
	now := time.Now().UnixMilli()
	next := cs.computeNextRun(sched, now)
	if next == nil {
		t.Fatal("expected non-nil next run")
	}
	if *next != now+5000 {
		t.Errorf("expected %d, got %d", now+5000, *next)
	}
}

func TestComputeNextRun_Every_NilEveryMS(t *testing.T) {
	cs := setupCronService(t)
	sched := &CronSchedule{Kind: "every", EveryMS: nil}
	next := cs.computeNextRun(sched, time.Now().UnixMilli())
	if next != nil {
		t.Error("expected nil for nil EveryMS")
	}
}

func TestComputeNextRun_Every_ZeroEveryMS(t *testing.T) {
	cs := setupCronService(t)
	zero := int64(0)
	sched := &CronSchedule{Kind: "every", EveryMS: &zero}
	next := cs.computeNextRun(sched, time.Now().UnixMilli())
	if next != nil {
		t.Error("expected nil for zero EveryMS")
	}
}

func TestComputeNextRun_Cron(t *testing.T) {
	cs := setupCronService(t)
	sched := &CronSchedule{Kind: "cron", Expr: "0 * * * *"}
	next := cs.computeNextRun(sched, time.Now().UnixMilli())
	if next == nil {
		t.Fatal("expected non-nil next run for cron expression")
	}
}

func TestComputeNextRun_Cron_EmptyExpr(t *testing.T) {
	cs := setupCronService(t)
	sched := &CronSchedule{Kind: "cron", Expr: ""}
	next := cs.computeNextRun(sched, time.Now().UnixMilli())
	if next != nil {
		t.Error("expected nil for empty cron expression")
	}
}

func TestComputeNextRun_Unknown(t *testing.T) {
	cs := setupCronService(t)
	sched := &CronSchedule{Kind: "unknown"}
	next := cs.computeNextRun(sched, time.Now().UnixMilli())
	if next != nil {
		t.Error("expected nil for unknown schedule kind")
	}
}

func TestExecuteJobByID_WithHandler(t *testing.T) {
	cs := setupCronService(t)
	var executed string

	cs.SetOnJob(func(job *CronJob) (string, error) {
		executed = job.ID
		return "done", nil
	})

	job, _ := cs.AddJob("exec", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "msg", false, "", "")
	cs.executeJobByID(job.ID)

	if executed != job.ID {
		t.Errorf("expected job %s to be executed, got %q", job.ID, executed)
	}

	jobs := cs.ListJobs(true)
	if jobs[0].State.LastStatus != "ok" {
		t.Errorf("expected LastStatus='ok', got %q", jobs[0].State.LastStatus)
	}
}

func TestExecuteJobByID_NotFound(t *testing.T) {
	cs := setupCronService(t)
	// Should not panic
	cs.executeJobByID("nonexistent")
}

func TestGenerateID_Uniqueness(t *testing.T) {
	ids := make(map[string]struct{})
	for i := 0; i < 100; i++ {
		id := generateID()
		if _, exists := ids[id]; exists {
			t.Errorf("duplicate ID generated: %s", id)
		}
		ids[id] = struct{}{}
	}
}

func TestLoadStore_MissingFile(t *testing.T) {
	cs := NewCronService("/nonexistent/path/jobs.json", nil)
	// Should not error (file not found is treated as empty)
	err := cs.Load()
	if err != nil {
		t.Errorf("expected no error for missing store, got: %v", err)
	}
}

func TestPersistence_RoundTrip(t *testing.T) {
	storePath := filepath.Join(t.TempDir(), "cron", "jobs.json")
	cs1 := NewCronService(storePath, nil)
	_, _ = cs1.AddJob("j1", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "msg", true, "telegram", "user")

	cs2 := NewCronService(storePath, nil)
	jobs := cs2.ListJobs(true)
	if len(jobs) != 1 {
		t.Fatalf("expected 1 job, got %d", len(jobs))
	}
	if jobs[0].Payload.Message != "msg" {
		t.Errorf("expected message 'msg', got %q", jobs[0].Payload.Message)
	}
	if !jobs[0].Payload.Deliver {
		t.Error("expected Deliver=true")
	}
}

func TestCheckJobs_ExecutesDueJobs(t *testing.T) {
	cs := setupCronService(t)
	var executed bool

	cs.SetOnJob(func(job *CronJob) (string, error) {
		executed = true
		return "", nil
	})

	cs.mu.Lock()
	cs.running = true
	pastMS := time.Now().Add(-time.Second).UnixMilli()
	job := CronJob{
		ID:       "due-job",
		Name:     "due",
		Enabled:  true,
		Schedule: CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)},
		Payload:  CronPayload{Message: "run me"},
		State:    CronJobState{NextRunAtMS: &pastMS},
	}
	cs.store.Jobs = append(cs.store.Jobs, job)
	cs.mu.Unlock()

	cs.checkJobs()

	// Give goroutine time to execute
	time.Sleep(100 * time.Millisecond)

	if !executed {
		t.Error("expected job to be executed when due")
	}
}

func TestGetNextWakeMS(t *testing.T) {
	cs := setupCronService(t)
	got := cs.getNextWakeMS()
	if got != nil {
		t.Error("expected nil when no jobs")
	}

	_, _ = cs.AddJob("j1", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")
	got = cs.getNextWakeMS()
	if got == nil {
		t.Error("expected non-nil when jobs exist")
	}
}

func TestFileNotExist_LoadStore(t *testing.T) {
	dir := t.TempDir()
	storePath := filepath.Join(dir, "nonexistent", "jobs.json")
	cs := NewCronService(storePath, nil)
	if cs.store == nil {
		t.Fatal("expected store to be initialized")
	}
	if len(cs.store.Jobs) != 0 {
		t.Errorf("expected empty store, got %d jobs", len(cs.store.Jobs))
	}
}

func TestSaveStore_PermissionsAfterAdd(t *testing.T) {
	dir := t.TempDir()
	storePath := filepath.Join(dir, "cron", "jobs.json")
	cs := NewCronService(storePath, nil)
	_, _ = cs.AddJob("j1", CronSchedule{Kind: "every", EveryMS: int64Ptr(1000)}, "m", false, "", "")

	// Verify file was created
	if _, err := os.Stat(storePath); os.IsNotExist(err) {
		t.Error("expected store file to exist")
	}
}
