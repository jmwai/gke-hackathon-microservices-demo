// Copyright 2018 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

// Agent communication data structures
type AgentRequest struct {
	AppName    string       `json:"appName"`
	UserID     string       `json:"userId"`
	SessionID  string       `json:"sessionId"`
	NewMessage AgentMessage `json:"newMessage"`
}

type AgentMessage struct {
	Role  string      `json:"role"`
	Parts []AgentPart `json:"parts"`
}

type AgentPart struct {
	Text       string `json:"text,omitempty"`
	ImageBytes []byte `json:"imageBytes,omitempty"`
}

type AgentResponse struct {
	Content  string          `json:"content"`
	Products []ProductResult `json:"products,omitempty"`
	Actions  []AgentAction   `json:"actions,omitempty"`
	Error    string          `json:"error,omitempty"`
}

type ProductResult struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"`
	Description string  `json:"description"`
	Price       string  `json:"price"`
	ImageURL    string  `json:"image_url"`
	Relevance   float64 `json:"relevance"`
	Distance    float64 `json:"distance,omitempty"`
}

type AgentAction struct {
	Type string                 `json:"type"`
	Data map[string]interface{} `json:"data,omitempty"`
}
