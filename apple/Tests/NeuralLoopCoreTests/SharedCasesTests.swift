import Foundation
import Testing
@testable import NeuralLoopCore

// The cases the Windows app's Python core runs too (testdata/core, read by windows/tests/test_shared_cases.py), so the
// two cores' rules can't drift apart: FSRS, progress merging, the prep window, and nudges.

private let casesFolder = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("testdata/core")

private func cases(_ name: String) throws -> [[String: Any]] {
    let data = try Data(contentsOf: casesFolder.appendingPathComponent(name))
    let parsed = try JSONSerialization.jsonObject(with: data)
    let file = try #require(parsed as? [String: Any])
    return try #require(file["cases"] as? [[String: Any]])
}

/// A part of a case (book.json, progress.json, …) decoded as the app decodes that file.
private func decode<T: Decodable>(_ type: T.Type, _ value: Any?) throws -> T {
    let object = value ?? [String: Any]()
    let data = try JSONSerialization.data(withJSONObject: object, options: [.fragmentsAllowed])
    return try JSONDecoder().decode(type, from: data)
}

private func close(_ a: Double, _ b: Double) -> Bool { abs(a - b) <= 1e-9 * max(1, abs(b)) }

@Test func sharedFSRSCases() throws {
    for c in try cases("fsrs.json") {
        let name = c["name"] as? String ?? "?"
        var card: CardState? = try c["card"] is NSNull ? nil : decode(CardState.self, c["card"])
        for step in try #require(c["steps"] as? [[String: Any]]) {
            let number = try #require(step["rating"] as? Int)
            let rating = try #require(Rating(rawValue: number))
            let now = try #require(step["now"] as? Double)
            card = FSRS.grade(card, rating, now: now)
        }
        let got = try #require(card)
        let expect = try decode(CardState.self, c["expect"])
        #expect(close(got.s, expect.s) && close(got.d, expect.d), "\(name): s \(got.s) d \(got.d)")
        #expect(got.reps == expect.reps && got.last == expect.last && got.due == expect.due, "\(name)")
    }
}

@Test func sharedProgressMergeCases() throws {
    for c in try cases("progress-merge.json") {
        let name = c["name"] as? String ?? "?"
        let devices = try #require(c["devices"] as? [Any]).map { try decode(StudyProgress.self, $0) }
        let got = c["sameDevice"] as? Bool == true
            ? StudyProgress.mergedSameDevice(devices[0], devices[1])
            : StudyProgress.merged(devices)
        let expect = try decode(StudyProgress.self, c["expect"])
        #expect(got == expect, "\(name)")
    }
}

@Test func sharedPrepWindowCases() throws {
    for c in try cases("prep-window.json") {
        let name = c["name"] as? String ?? "?"
        let book: Book? = try c["book"] is NSNull ? nil : decode(Book.self, c["book"])
        let progress = try decode(StudyProgress.self, c["progress"])
        let window = PrepWindow.make(book: book, progress: progress, everything: c["everything"] as? Bool ?? false)
        let expect = try #require(c["expect"] as? [String: Any])
        #expect(window.chaptersSpec == expect["chapters"] as? String, "\(name): chapters \(window.chaptersSpec)")
        #expect(window.mediaSpec == expect["media"] as? String, "\(name): media \(window.mediaSpec)")
        if let book {
            #expect(window.hasWork(book) == expect["hasWork"] as? Bool, "\(name): hasWork")
        } else {
            #expect(expect["hasWork"] is NSNull, "\(name): no book, no hasWork")
        }
    }
}

@Test func sharedNudgeCases() throws {
    for c in try cases("nudges.json") {
        let name = c["name"] as? String ?? "?"
        let pairs = try #require(c["books"] as? [[String: Any]])
        var books: [(book: Book, progress: StudyProgress)] = []
        for pair in pairs {
            books.append((book: try decode(Book.self, pair["book"]), progress: try decode(StudyProgress.self, pair["progress"])))
        }
        let settings = try decode(NudgeSettings.self, c["settings"])
        let history = try decode(NudgeHistory.self, c["history"])
        let now = try #require(c["now"] as? Double)
        let hour = try #require(c["hour"] as? Int)
        let today = try #require(c["today"] as? String)
        let got = Nudges.decide(books: books, settings: settings, history: history, now: now, hour: hour, today: today,
                                appActive: c["appActive"] as? Bool ?? false)
        if let expect = c["expect"] as? [String: Any] {
            #expect(got?.title == expect["title"] as? String, "\(name): title \(got?.title ?? "none")")
            #expect(got?.body == expect["body"] as? String, "\(name): body \(got?.body ?? "none")")
            #expect(got?.mood.rawValue == expect["mood"] as? String, "\(name): mood")
        } else {
            #expect(got == nil, "\(name): expected no nudge, got \(got?.title ?? "")")
        }
    }
}
